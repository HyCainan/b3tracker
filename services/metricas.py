"""
Métricas técnicas do B3Tracker (base do Capítulo 6 do TCC).

Decisões metodológicas aplicadas aqui:
- Renda fixa (CDI/Selic, ticker entre colchetes, fonte bcb) é separada das
  ações: por padrão as métricas consideram só `categoria="acoes"`.
- brapi e yfinance são tratadas como "fonte externa" (sem distinção nas
  tabelas de métricas); o detalhe de cada fonte fica na descrição do sistema.
- A janela de análise pode ser por `dias` ou por `data_inicio`/`data_fim`,
  para isolar regimes de coleta distintos (ex.: antes/depois do bloqueio de
  ranges da brapi em 29/10/2026).

Uso para exportar os dados do Cap. 6 (na raiz do projeto):
    python -m services.metricas --inicio 2026-10-29 --pasta exports
"""

import csv
import os
from datetime import date, datetime, timedelta

from db.database import get_connection

CATEGORIAS = ("acoes", "renda_fixa", "todas")

# Abaixo disso, p95/p99 são interpolados de pouquíssimas amostras.
AMOSTRA_MINIMA_PERCENTIS = 30


# =========================
# Helpers internos
# =========================


def _normalizar_data(valor, fim=False):
    """
    Converte date/datetime/str ISO em string ISO. Para o limite final dado
    só como data (sem hora), soma 1 dia: o intervalo é [inicio, fim) e o
    dia informado entra por inteiro.
    """
    if isinstance(valor, datetime):
        dt, somente_data = valor, False
    elif isinstance(valor, date):
        dt, somente_data = datetime.combine(valor, datetime.min.time()), True
    else:
        texto = str(valor).strip()
        dt, somente_data = datetime.fromisoformat(texto), len(texto) == 10

    if fim and somente_data:
        dt += timedelta(days=1)

    return dt.isoformat()


def _janela(dias, data_inicio, data_fim):
    if data_inicio is not None:
        desde = _normalizar_data(data_inicio)
    else:
        desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    ate = _normalizar_data(data_fim, fim=True) if data_fim is not None else None
    return desde, ate


def _where(desde, ate, categoria=None):
    cond = ["registrado_em >= ?"]
    params = [desde]

    if ate:
        cond.append("registrado_em < ?")
        params.append(ate)

    if categoria is not None:
        if categoria not in CATEGORIAS:
            raise ValueError(f"categoria deve ser uma de {CATEGORIAS}")
        # Renda fixa é gravada com o indexador entre colchetes (ex.: "[CDI]").
        if categoria == "acoes":
            cond.append("ticker NOT LIKE '[%'")
        elif categoria == "renda_fixa":
            cond.append("ticker LIKE '[%'")

    return " AND ".join(cond), params


def _buscar_linhas(dias, categoria, data_inicio, data_fim):
    desde, ate = _janela(dias, data_inicio, data_fim)
    where, params = _where(desde, ate, categoria)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM log_requisicoes WHERE {where} ORDER BY registrado_em DESC",
        params,
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        eh_rf = str(r["ticker"]).startswith("[")
        r["categoria"] = "renda_fixa" if eh_rf else "acoes"
        r["grupo_fonte"] = "indexador (BCB)" if eh_rf else "fonte externa"

    return rows


def _percentil(dados, p):
    """Percentil por interpolação linear entre as duas amostras mais próximas."""
    if len(dados) == 1:
        return dados[0]
    k = (len(dados) - 1) * (p / 100)
    piso = int(k)
    teto = min(piso + 1, len(dados) - 1)
    if piso == teto:
        return dados[piso]
    return dados[piso] + (dados[teto] - dados[piso]) * (k - piso)


# =========================
# Resumo geral
# =========================


def resumo_metricas(dias=7, categoria="acoes", data_inicio=None, data_fim=None):
    """
    Resumo das métricas de `log_requisicoes` na janela escolhida.

    Cada linha do log é uma TENTATIVA. Quando a brapi falha e o yfinance
    atende, são duas linhas (uma falha, uma sucesso): `taxa_erro` mede erro
    por tentativa, não requisições que terminaram sem dados para o usuário.
    """
    rows = _buscar_linhas(dias, categoria, data_inicio, data_fim)
    total = len(rows)

    if total == 0:
        return {
            "categoria": categoria,
            "total": 0,
            "cache_hits": 0,
            "chamadas_api": 0,
            "taxa_cache_hit": 0.0,
            "tempo_medio_cache_ms": 0.0,
            "tempo_medio_api_ms": 0.0,
            "reducao_tempo_pct": 0.0,
            "chamadas_evitadas": 0,
            "tempo_total_economizado_ms": 0.0,
            "taxa_erro": 0.0,
            "total_erros": 0,
            "linhas": [],
        }

    cache_hits = [
        r for r in rows if r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]

    chamadas_api = [
        r
        for r in rows
        if not r["veio_do_cache"]
        and r["sucesso"]
        and r["tempo_resposta_ms"] is not None
    ]

    erros = [r for r in rows if not r["sucesso"]]

    tempo_medio_cache_ms = (
        sum(r["tempo_resposta_ms"] for r in cache_hits) / len(cache_hits)
        if cache_hits
        else 0.0
    )

    tempo_medio_api_ms = (
        sum(r["tempo_resposta_ms"] for r in chamadas_api) / len(chamadas_api)
        if chamadas_api
        else 0.0
    )

    if tempo_medio_api_ms > 0:
        reducao_tempo_pct = (
            (tempo_medio_api_ms - tempo_medio_cache_ms) / tempo_medio_api_ms
        ) * 100
    else:
        reducao_tempo_pct = 0.0

    reducao_tempo_pct = max(reducao_tempo_pct, 0.0)

    chamadas_evitadas = len(cache_hits)

    ganho_por_chamada_ms = max(tempo_medio_api_ms - tempo_medio_cache_ms, 0.0)
    tempo_total_economizado_ms = chamadas_evitadas * ganho_por_chamada_ms

    return {
        "categoria": categoria,
        "total": total,
        "cache_hits": len(cache_hits),
        "chamadas_api": len(chamadas_api),
        "taxa_cache_hit": (len(cache_hits) / total) * 100,
        "tempo_medio_cache_ms": tempo_medio_cache_ms,
        "tempo_medio_api_ms": tempo_medio_api_ms,
        "reducao_tempo_pct": reducao_tempo_pct,
        "chamadas_evitadas": chamadas_evitadas,
        "tempo_total_economizado_ms": tempo_total_economizado_ms,
        "taxa_erro": (len(erros) / total) * 100,
        "total_erros": len(erros),
        "linhas": rows,
    }


def comparacao_cache_api(dias=7, categoria="acoes", data_inicio=None, data_fim=None):
    """Métricas de cache vs. fonte externa (reaproveita resumo_metricas)."""
    resumo = resumo_metricas(dias, categoria, data_inicio, data_fim)

    return {
        "total": resumo["total"],
        "cache_hits": resumo["cache_hits"],
        "chamadas_api": resumo["chamadas_api"],
        "tempo_medio_cache_ms": resumo["tempo_medio_cache_ms"],
        "tempo_medio_api_ms": resumo["tempo_medio_api_ms"],
        "fator_aceleracao": (
            resumo["tempo_medio_api_ms"] / resumo["tempo_medio_cache_ms"]
            if resumo["tempo_medio_cache_ms"] > 0
            else 0.0
        ),
        "tempo_economizado_estimado_ms": resumo["tempo_total_economizado_ms"],
        "chamadas_evitadas_pct": resumo["taxa_cache_hit"],
    }


def erros_por_ticker(dias=7, categoria="acoes", data_inicio=None, data_fim=None):
    """Quantidade de tentativas com erro por ticker na janela."""
    desde, ate = _janela(dias, data_inicio, data_fim)
    where, params = _where(desde, ate, categoria)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT ticker, COUNT(*) AS total_erros
        FROM log_requisicoes
        WHERE {where} AND sucesso = 0
        GROUP BY ticker
        ORDER BY total_erros DESC
        """,
        params,
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


# =========================
# Percentis de latência
# =========================


def percentis_latencia_api(dias=7, categoria="acoes", data_inicio=None, data_fim=None):
    """
    Percentis (p50/p90/p95/p99), mínimo e máximo das chamadas reais à fonte
    externa (sem cache, com sucesso). `amostra_pequena` sinaliza N abaixo de
    AMOSTRA_MINIMA_PERCENTIS: nesse caso p95/p99 são interpolados de poucas
    amostras e devem ser lidos com cautela.
    """
    rows = _buscar_linhas(dias, categoria, data_inicio, data_fim)

    tempos = sorted(
        r["tempo_resposta_ms"]
        for r in rows
        if not r["veio_do_cache"]
        and r["sucesso"]
        and r["tempo_resposta_ms"] is not None
    )

    if not tempos:
        return {
            "amostras": 0,
            "amostra_pequena": True,
            "min_ms": 0.0,
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "tempos": [],
        }

    return {
        "amostras": len(tempos),
        "amostra_pequena": len(tempos) < AMOSTRA_MINIMA_PERCENTIS,
        "min_ms": tempos[0],
        "p50_ms": _percentil(tempos, 50),
        "p90_ms": _percentil(tempos, 90),
        "p95_ms": _percentil(tempos, 95),
        "p99_ms": _percentil(tempos, 99),
        "max_ms": tempos[-1],
        "tempos": tempos,
    }


# =========================
# Paralelo vs. sequencial
# =========================


def _buscar_lotes(dias, data_inicio, data_fim):
    desde, ate = _janela(dias, data_inicio, data_fim)
    where, params = _where(desde, ate)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM log_buscas_lote WHERE {where} ORDER BY registrado_em DESC",
        params,
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def comparacao_paralelo_sequencial(
    dias=7, data_inicio=None, data_fim=None, qtd_tickers=None
):
    """
    Compara o tempo total de busca em lote entre os modos paralelo e
    sequencial. `qtd_tickers` restringe a comparação a lotes do mesmo
    tamanho, o que evita comparar lotes de 2 ativos com lotes de 8.

    Atenção: o log de lote não registra quantos ativos vieram do cache, então
    a comparação só é limpa se os dois modos forem rodados com cache frio.
    """
    rows = _buscar_lotes(dias, data_inicio, data_fim)

    if qtd_tickers is not None:
        rows = [r for r in rows if r["qtd_tickers"] == qtd_tickers]

    paralelas = [r for r in rows if r["modo"] == "paralelo"]
    sequenciais = [r for r in rows if r["modo"] == "sequencial"]

    def _media(lista, campo):
        return sum(r[campo] for r in lista) / len(lista) if lista else 0.0

    tempo_medio_paralelo = _media(paralelas, "tempo_total_ms")
    tempo_medio_sequencial = _media(sequenciais, "tempo_total_ms")

    fator_speedup = (
        tempo_medio_sequencial / tempo_medio_paralelo
        if tempo_medio_paralelo > 0
        else 0.0
    )

    return {
        "total_paralelo": len(paralelas),
        "total_sequencial": len(sequenciais),
        "tempo_medio_paralelo_ms": tempo_medio_paralelo,
        "tempo_medio_sequencial_ms": tempo_medio_sequencial,
        "fator_speedup": fator_speedup,
        "media_tickers_paralelo": _media(paralelas, "qtd_tickers"),
        "media_tickers_sequencial": _media(sequenciais, "qtd_tickers"),
        "linhas": rows,
    }


# =========================
# Exportação para o Capítulo 6
# =========================

_COLUNAS_REQ = [
    "id",
    "ticker",
    "categoria",
    "periodo",
    "veio_do_cache",
    "sucesso",
    "tempo_resposta_ms",
    "erro",
    "registrado_em",
    "fonte",
    "grupo_fonte",
]

_COLUNAS_LOTE = ["id", "modo", "qtd_tickers", "tempo_total_ms", "registrado_em"]


def _gravar_csv(caminho, colunas, linhas):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)


def exportar_dados(pasta="exports", dias=3650, data_inicio=None, data_fim=None):
    """
    Exporta log_requisicoes (todas as categorias, com a coluna `categoria`
    para filtrar depois) e log_buscas_lote em CSV, na janela escolhida.
    Retorna os caminhos gerados.
    """
    os.makedirs(pasta, exist_ok=True)

    requisicoes = _buscar_linhas(dias, "todas", data_inicio, data_fim)
    lotes = _buscar_lotes(dias, data_inicio, data_fim)

    caminho_req = os.path.join(pasta, "log_requisicoes.csv")
    caminho_lote = os.path.join(pasta, "log_buscas_lote.csv")

    _gravar_csv(caminho_req, _COLUNAS_REQ, requisicoes)
    _gravar_csv(caminho_lote, _COLUNAS_LOTE, lotes)

    return {
        "requisicoes": caminho_req,
        "qtd_requisicoes": len(requisicoes),
        "lotes": caminho_lote,
        "qtd_lotes": len(lotes),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporta os logs para o Cap. 6.")
    parser.add_argument("--inicio", help="data inicial (AAAA-MM-DD)")
    parser.add_argument("--fim", help="data final, inclusive (AAAA-MM-DD)")
    parser.add_argument("--pasta", default="exports")
    args = parser.parse_args()

    resultado = exportar_dados(
        pasta=args.pasta, data_inicio=args.inicio, data_fim=args.fim
    )
    print(resultado)
