import json
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

from db.database import get_connection

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
    if data.get("results"):
        return data["results"][0]
    return None


def _registrar_log(
    ticker, periodo, veio_do_cache, sucesso, tempo_resposta_ms, erro=None
):
    """
    Registra uma linha de métricas na tabela log_requisicoes: se a consulta
    veio do cache ou da API, se teve sucesso, quanto tempo levou e o erro
    (se houver). Usado pela página de Métricas para calcular indicadores
    de desempenho e qualidade de dados.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO log_requisicoes
            (ticker, periodo, veio_do_cache, sucesso, tempo_resposta_ms, erro, registrado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            periodo,
            1 if veio_do_cache else 0,
            1 if sucesso else 0,
            tempo_resposta_ms,
            erro,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def buscar_ativo(ticker, periodo, token, ttl_minutos=15):
    """
    Busca a cotação de um ticker respeitando o cache local com TTL.
    Retorna (dados, veio_do_cache).
    A chave de cache combina ticker + período pois o histórico varia por período.

    Cada chamada gera automaticamente uma linha em log_requisicoes com o
    tempo de resposta, se veio do cache e se teve sucesso — base para as
    métricas técnicas do projeto. O tempo de resposta é sempre medido de
    verdade (tanto para cache quanto para API), para permitir a comparação
    honesta de desempenho entre os dois caminhos.
    """
    t_inicio = time.perf_counter()

    conn = get_connection()
    cur = conn.cursor()

    chave = f"{ticker}:{periodo}"
    cur.execute(
        "SELECT dados_json, coletado_em FROM cache_cotacoes WHERE ticker = ?", (chave,)
    )
    row = cur.fetchone()

    if row is not None:
        coletado_em = datetime.fromisoformat(row["coletado_em"])
        if datetime.utcnow() - coletado_em < timedelta(minutes=ttl_minutos):
            # Inclui a desserialização do JSON na medição: é o custo real
            # de "resolver" a requisição pelo cache, ponto de comparação
            # justo contra o tempo de uma chamada real à API.
            dados = json.loads(row["dados_json"])
            conn.close()
            tempo_resposta_ms = (time.perf_counter() - t_inicio) * 1000
            _registrar_log(
                ticker,
                periodo,
                veio_do_cache=True,
                sucesso=True,
                tempo_resposta_ms=tempo_resposta_ms,
            )
            return dados, True

    inicio_api = time.perf_counter()

    try:
        dados = _chamar_api(ticker, periodo, token)
    except Exception as e:
        tempo_resposta_ms = (time.perf_counter() - inicio_api) * 1000
        conn.close()
        _registrar_log(
            ticker,
            periodo,
            veio_do_cache=False,
            sucesso=False,
            tempo_resposta_ms=tempo_resposta_ms,
            erro=str(e),
        )
        raise

    tempo_resposta_ms = (time.perf_counter() - inicio_api) * 1000

    if dados is not None:
        cur.execute(
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

    _registrar_log(
        ticker,
        periodo,
        veio_do_cache=False,
        sucesso=dados is not None,
        tempo_resposta_ms=tempo_resposta_ms,
        erro=None if dados is not None else "Nenhum resultado retornado pela API",
    )

    return dados, False


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
    ... (docstring original) ...
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
