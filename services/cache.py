import json
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import threading
import yfinance as yf
from db.database import get_connection

# Limita requisições simultâneas ao Yahoo para evitar HTTP 429.
_SEM_YFINANCE = threading.Semaphore(3)

yf.config.debug.hide_exceptions = False

TICKERS_DISPONIVEIS = [
    "PETR4",
    "VALE3",
    "MGLU3",
    "ITUB4",
    "BBDC4",
    "ABEV3",
    "WEGE3",
    "RENT3",
    "BBAS3",
    "EGIE3",
    "RADL3",
    "SUZB3",
    "RAIL3",
    "TOTS3",
    "HAPV3",
    "B3SA3",
    "BBSE3",
    "EQTL3",
    "ISAE4",
    "VIVT3",
    "EMBJ3",
    "BPAC11",
    "CPLE3",
    "TAEE11",
    "RDOR3",
]
PERIODOS = {
    "1 mês": "1mo",
    "3 meses": "3mo",
    "6 meses": "6mo",
    "1 ano": "1y",
}


def _chamar_api(ticker, periodo, token):
    url = f"https://brapi.dev/api/quote/{ticker}?range={periodo}&interval=1d&token={token}"
    response = requests.get(url, timeout=10)
    data = response.json()

    if response.status_code != 200:
        msg = data.get("message") or data.get("error") or response.text[:200]
        raise RuntimeError(f"brapi HTTP {response.status_code}: {msg}")

    if data.get("results"):
        return data["results"][0]
    return None


def _chamar_yfinance(ticker, periodo):
    """
    Busca o histórico no Yahoo Finance e devolve no mesmo formato da brapi
    (symbol, regularMarket*, historicalDataPrice), para que Dashboard e
    Recomendações funcionem sem alteração. O "preço atual" é o último
    fechamento disponível.
    """
    with _SEM_YFINANCE:
        df = yf.Ticker(f"{ticker}.SA").history(period=periodo, interval="1d")

    if df is None or df.empty:
        return None

    df = df.dropna(subset=["Close"])
    if df.empty:
        return None

    historico = [
        {
            "date": int(idx.timestamp()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in df.iterrows()
    ]

    ultimo = historico[-1]
    anterior = historico[-2]["close"] if len(historico) > 1 else ultimo["close"]
    variacao = (ultimo["close"] / anterior - 1) * 100 if anterior else 0.0

    return {
        "symbol": ticker,
        "regularMarketPrice": ultimo["close"],
        "regularMarketChangePercent": variacao,
        "regularMarketDayHigh": ultimo["high"],
        "regularMarketDayLow": ultimo["low"],
        "regularMarketVolume": ultimo["volume"],
        "historicalDataPrice": historico,
    }


def _fontes_para(periodo):
    """Ordem de tentativa para qualquer período: brapi primeiro, yfinance como fallback."""
    return ["brapi", "yfinance"]


def _registrar_log(
    ticker, periodo, veio_do_cache, sucesso, tempo_resposta_ms, erro=None, fonte=None
):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO log_requisicoes
            (ticker, periodo, veio_do_cache, sucesso, tempo_resposta_ms, erro, registrado_em, fonte)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            periodo,
            1 if veio_do_cache else 0,
            1 if sucesso else 0,
            tempo_resposta_ms,
            erro,
            datetime.utcnow().isoformat(),
            fonte,
        ),
    )
    conn.commit()
    conn.close()


def _salvar_cache(chave, dados):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO cache_cotacoes (ticker, dados_json, coletado_em)
        VALUES (?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            dados_json = excluded.dados_json,
            coletado_em = excluded.coletado_em
        """,
        (chave, json.dumps(dados), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def buscar_ativo(ticker, periodo, token, ttl_minutos=15):
    """
    Busca a cotação respeitando o cache local com TTL. Retorna (dados, veio_do_cache).
    Fonte primária: brapi (onde o plano permite); fallback: yfinance.
    Cada tentativa gera uma linha em log_requisicoes com a fonte usada.
    """
    t_inicio = time.perf_counter()
    chave = f"{ticker}:{periodo}"

    conn = get_connection()
    row = conn.execute(
        "SELECT dados_json, coletado_em FROM cache_cotacoes WHERE ticker = ?", (chave,)
    ).fetchone()
    conn.close()

    if row is not None:
        coletado_em = datetime.fromisoformat(row["coletado_em"])
        if datetime.utcnow() - coletado_em < timedelta(minutes=ttl_minutos):
            dados = json.loads(row["dados_json"])
            tempo_resposta_ms = (time.perf_counter() - t_inicio) * 1000
            _registrar_log(
                ticker,
                periodo,
                True,
                True,
                tempo_resposta_ms,
                fonte=dados.get("_fonte", "brapi"),
            )
            return dados, True

    ultima_excecao = None

    for fonte in _fontes_para(periodo):
        inicio_api = time.perf_counter()
        dados, erro = None, None

        try:
            if fonte == "brapi":
                dados = _chamar_api(ticker, periodo, token)
            else:
                dados = _chamar_yfinance(ticker, periodo)
            if dados is None:
                erro = "Nenhum resultado retornado pela API"
        except Exception as e:
            erro = str(e)
            ultima_excecao = e

        tempo_resposta_ms = (time.perf_counter() - inicio_api) * 1000

        _registrar_log(
            ticker,
            periodo,
            False,
            dados is not None,
            tempo_resposta_ms,
            erro=erro,
            fonte=fonte,
        )

        if dados is not None:
            dados["_fonte"] = fonte
            _salvar_cache(chave, dados)
            return dados, False

    if ultima_excecao is not None:
        raise ultima_excecao

    return None, False


def _registrar_log_lote(modo, qtd_tickers, tempo_total_ms):
    """
    Registra uma chamada de busca em lote (paralela ou sequencial) para
    alimentar o comparativo de desempenho apresentado nas Métricas técnicas.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO log_buscas_lote (modo, qtd_tickers, tempo_total_ms, registrado_em)
        VALUES (?, ?, ?, ?)
        """,
        (modo, qtd_tickers, tempo_total_ms, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def buscar_ativos_paralelo(tickers, periodo, token, max_workers=8, paralelo=True):
    """
    Busca vários tickers de uma vez. Retorna uma lista de tuplas
    (ticker, stock, veio_do_cache, erro), na mesma ordem de `tickers`.

    paralelo=True usa ThreadPoolExecutor (até `max_workers` threads);
    paralelo=False busca um por vez. Os dois modos registram o tempo total
    em log_buscas_lote, para o comparativo de desempenho nas Métricas.
    """
    if not tickers:
        return []

    t_inicio_lote = time.perf_counter()
    modo = "paralelo" if paralelo else "sequencial"

    if not paralelo:
        resultados_seq = []
        for ticker in tickers:
            try:
                stock, veio_do_cache = buscar_ativo(ticker, periodo, token)
                resultados_seq.append((ticker, stock, veio_do_cache, None))
            except Exception as e:
                resultados_seq.append((ticker, None, False, str(e)))

        tempo_total_ms = (time.perf_counter() - t_inicio_lote) * 1000
        _registrar_log_lote(modo, len(tickers), tempo_total_ms)
        return resultados_seq

    resultados = {}
    workers = max(1, min(max_workers, len(tickers)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {
            executor.submit(buscar_ativo, ticker, periodo, token): ticker
            for ticker in tickers
        }

        for futuro in as_completed(futuros):
            ticker = futuros[futuro]
            try:
                stock, veio_do_cache = futuro.result()
                resultados[ticker] = (stock, veio_do_cache, None)
            except Exception as e:
                resultados[ticker] = (None, False, str(e))

    tempo_total_ms = (time.perf_counter() - t_inicio_lote) * 1000
    _registrar_log_lote(modo, len(tickers), tempo_total_ms)

    return [(ticker, *resultados[ticker]) for ticker in tickers]
