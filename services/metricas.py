from datetime import datetime, timedelta

from db.database import get_connection


def resumo_metricas(dias=7):
    """
    Calcula um resumo das métricas técnicas coletadas em log_requisicoes
    nos últimos `dias` dias: total de requisições, taxa de cache hit,
    tempo médio de resposta da API (apenas chamadas reais, sem cache) e
    taxa de erro.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        "SELECT * FROM log_requisicoes WHERE registrado_em >= ? ORDER BY registrado_em DESC",
        (desde,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    total = len(rows)

    if total == 0:
        return {
            "total": 0,
            "cache_hits": 0,
            "taxa_cache_hit": 0.0,
            "tempo_medio_api_ms": 0.0,
            "taxa_erro": 0.0,
            "total_erros": 0,
            "linhas": [],
        }

    cache_hits = sum(1 for r in rows if r["veio_do_cache"])
    erros = [r for r in rows if not r["sucesso"]]

    chamadas_api = [
        r for r in rows if not r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]

    tempo_medio_api_ms = (
        sum(r["tempo_resposta_ms"] for r in chamadas_api) / len(chamadas_api)
        if chamadas_api
        else 0.0
    )

    return {
        "total": total,
        "cache_hits": cache_hits,
        "taxa_cache_hit": cache_hits / total * 100,
        "tempo_medio_api_ms": tempo_medio_api_ms,
        "taxa_erro": len(erros) / total * 100,
        "total_erros": len(erros),
        "linhas": rows,
    }


def erros_por_ticker(dias=7):
    """
    Retorna a contagem de erros agrupada por ticker no período, para
    identificar ativos com problemas recorrentes na integração com a API.
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        """
        SELECT ticker, COUNT(*) as total_erros
        FROM log_requisicoes
        WHERE registrado_em >= ? AND sucesso = 0
        GROUP BY ticker
        ORDER BY total_erros DESC
        """,
        (desde,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def comparacao_cache_api(dias=7):
    """
    Compara o desempenho do caminho de cache com o caminho de chamada real
    à API dentro do período, para evidenciar o ganho de desempenho trazido
    pelo cache — um dos objetivos centrais do TCC ("validar a eficácia do
    cache inteligente através da redução mensurável do tempo de resposta").

    Retorna, entre outras coisas, uma estimativa de tempo economizado: o
    tempo que teria sido gasto se cada cache hit tivesse, em vez disso,
    sido uma chamada real à API (usando o tempo médio real de API
    observado no mesmo período como referência).
    """
    conn = get_connection()
    cur = conn.cursor()

    desde = (datetime.utcnow() - timedelta(days=dias)).isoformat()

    cur.execute(
        "SELECT * FROM log_requisicoes WHERE registrado_em >= ?",
        (desde,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    total = len(rows)

    if total == 0:
        return {
            "total": 0,
            "cache_hits": 0,
            "chamadas_api": 0,
            "tempo_medio_cache_ms": 0.0,
            "tempo_medio_api_ms": 0.0,
            "fator_aceleracao": 0.0,
            "tempo_economizado_estimado_ms": 0.0,
            "chamadas_evitadas_pct": 0.0,
        }

    hits_cache = [
        r for r in rows if r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]
    chamadas_api = [
        r for r in rows if not r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]

    tempo_medio_cache_ms = (
        sum(r["tempo_resposta_ms"] for r in hits_cache) / len(hits_cache)
        if hits_cache
        else 0.0
    )
    tempo_medio_api_ms = (
        sum(r["tempo_resposta_ms"] for r in chamadas_api) / len(chamadas_api)
        if chamadas_api
        else 0.0
    )

    fator_aceleracao = (
        tempo_medio_api_ms / tempo_medio_cache_ms if tempo_medio_cache_ms > 0 else 0.0
    )

    tempo_economizado_estimado_ms = len(hits_cache) * max(
        tempo_medio_api_ms - tempo_medio_cache_ms, 0.0
    )

    return {
        "total": total,
        "cache_hits": len(hits_cache),
        "chamadas_api": len(chamadas_api),
        "tempo_medio_cache_ms": tempo_medio_cache_ms,
        "tempo_medio_api_ms": tempo_medio_api_ms,
        "fator_aceleracao": fator_aceleracao,
        "tempo_economizado_estimado_ms": tempo_economizado_estimado_ms,
        "chamadas_evitadas_pct": len(hits_cache) / total * 100,
    }


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
        WHERE registrado_em >= ? AND veio_do_cache = 0 AND tempo_resposta_ms IS NOT NULL
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
