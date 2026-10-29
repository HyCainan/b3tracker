from datetime import datetime, timedelta

from db.database import get_connection


def resumo_metricas(dias=7):
    """
    Calcula o resumo das métricas técnicas coletadas em log_requisicoes
    nos últimos `dias` dias.

    Inclui:
    - volume total de requisições;
    - taxa de cache hit;
    - tempo médio da API;
    - tempo médio do cache;
    - redução percentual de tempo;
    - chamadas evitadas na API;
    - tempo total estimado economizado;
    - taxa e quantidade de erros;
    - linhas detalhadas do log.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        """
        SELECT *
        FROM log_requisicoes
        WHERE registrado_em >= ?
        ORDER BY registrado_em DESC
        """,
        (desde,),
    )

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    total = len(rows)

    # ---------------------------------------------------------
    # Sem dados
    # ---------------------------------------------------------

    if total == 0:
        return {
            "total": 0,
            "cache_hits": 0,
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

    # ---------------------------------------------------------
    # Cache
    # ---------------------------------------------------------

    cache_hits = [
        r for r in rows if r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]

    # ---------------------------------------------------------
    # Chamadas reais à API
    # ---------------------------------------------------------

    chamadas_api = [
        r
        for r in rows
        if not r["veio_do_cache"]
        and r["sucesso"]
        and r["tempo_resposta_ms"] is not None
    ]

    # ---------------------------------------------------------
    # Erros
    # ---------------------------------------------------------

    erros = [r for r in rows if not r["sucesso"]]

    # ---------------------------------------------------------
    # Tempo médio do cache
    # ---------------------------------------------------------

    tempo_medio_cache_ms = (
        sum(r["tempo_resposta_ms"] for r in cache_hits) / len(cache_hits)
        if cache_hits
        else 0.0
    )

    # ---------------------------------------------------------
    # Tempo médio da API
    # ---------------------------------------------------------

    tempo_medio_api_ms = (
        sum(r["tempo_resposta_ms"] for r in chamadas_api) / len(chamadas_api)
        if chamadas_api
        else 0.0
    )

    # ---------------------------------------------------------
    # Redução percentual proporcionada pelo cache
    #
    # Exemplo:
    # API   = 500 ms
    # Cache = 5 ms
    #
    # redução = 99%
    # ---------------------------------------------------------

    if tempo_medio_api_ms > 0:
        reducao_tempo_pct = (
            (tempo_medio_api_ms - tempo_medio_cache_ms) / tempo_medio_api_ms
        ) * 100
    else:
        reducao_tempo_pct = 0.0

    # Evita percentual negativo em situações anômalas.
    reducao_tempo_pct = max(reducao_tempo_pct, 0.0)

    # ---------------------------------------------------------
    # Chamadas evitadas
    # ---------------------------------------------------------

    chamadas_evitadas = len(cache_hits)

    # ---------------------------------------------------------
    # Tempo total estimado economizado
    #
    # Estimativa:
    #
    # nº de cache hits ×
    # (tempo médio API - tempo médio cache)
    # ---------------------------------------------------------

    ganho_por_chamada_ms = max(
        tempo_medio_api_ms - tempo_medio_cache_ms,
        0.0,
    )

    tempo_total_economizado_ms = chamadas_evitadas * ganho_por_chamada_ms

    # ---------------------------------------------------------
    # Resultado
    # ---------------------------------------------------------

    return {
        "total": total,
        "cache_hits": len(cache_hits),
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


def comparacao_cache_api(dias=7):
    """
    Retorna exclusivamente as métricas relacionadas à comparação
    entre cache e API.

    Reutiliza resumo_metricas() para evitar duplicação de regras
    de negócio e cálculos.
    """
    resumo = resumo_metricas(dias)

    return {
        "total": resumo["total"],
        "cache_hits": resumo["cache_hits"],
        "chamadas_api": resumo["total"] - resumo["cache_hits"],
        "tempo_medio_cache_ms": resumo["tempo_medio_cache_ms"],
        "tempo_medio_api_ms": resumo["tempo_medio_api_ms"],
        "fator_aceleracao": (
            resumo["tempo_medio_api_ms"] / resumo["tempo_medio_cache_ms"]
            if resumo["tempo_medio_cache_ms"] > 0
            else 0.0
        ),
        "tempo_economizado_estimado_ms": (resumo["tempo_total_economizado_ms"]),
        "chamadas_evitadas_pct": (resumo["taxa_cache_hit"]),
    }


def erros_por_ticker(dias=7):
    """
    Retorna a quantidade de erros agrupada por ticker
    dentro do período informado.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        """
        SELECT ticker, COUNT(*) AS total_erros
        FROM log_requisicoes
        WHERE registrado_em >= ?
          AND sucesso = 0
        GROUP BY ticker
        ORDER BY total_erros DESC
        """,
        (desde,),
    )

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def percentis_latencia_api(dias=7):
    """
    Calcula percentis de latência (p50/p90/p95/p99), mínimo e máximo das
    chamadas reais à API no período. Percentis dão uma leitura mais
    robusta do desempenho do que a média isolada, já que expõem picos de
    latência (cauda da distribuição) que a média pode mascarar.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        """
        SELECT tempo_resposta_ms FROM log_requisicoes
        WHERE registrado_em >= ? AND veio_do_cache = 0 AND sucesso = 1
            AND tempo_resposta_ms IS NOT NULL
        """,
        (desde,),
    )
    tempos = sorted(r["tempo_resposta_ms"] for r in cur.fetchall())
    conn.close()

    if not tempos:
        return {
            "amostras": 0,
            "min_ms": 0.0,
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "tempos": [],
        }

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

    return {
        "amostras": len(tempos),
        "min_ms": tempos[0],
        "p50_ms": _percentil(tempos, 50),
        "p90_ms": _percentil(tempos, 90),
        "p95_ms": _percentil(tempos, 95),
        "p99_ms": _percentil(tempos, 99),
        "max_ms": tempos[-1],
        "tempos": tempos,
    }


def comparacao_paralelo_sequencial(dias=7):
    """
    Compara o tempo total de busca em lote entre os modos paralelo e
    sequencial (services.cache.buscar_ativos_paralelo), agrupando por modo.
    Base do experimento comparativo de paralelismo do TCC.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        """
        SELECT * FROM log_buscas_lote
        WHERE registrado_em >= ?
        ORDER BY registrado_em DESC
        """,
        (desde,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

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

    media_tickers_paralelo = _media(paralelas, "qtd_tickers")
    media_tickers_sequencial = _media(sequenciais, "qtd_tickers")

    return {
        "total_paralelo": len(paralelas),
        "total_sequencial": len(sequenciais),
        "tempo_medio_paralelo_ms": tempo_medio_paralelo,
        "tempo_medio_sequencial_ms": tempo_medio_sequencial,
        "fator_speedup": fator_speedup,
        "media_tickers_paralelo": media_tickers_paralelo,
        "media_tickers_sequencial": media_tickers_sequencial,
        "linhas": rows,
    }
