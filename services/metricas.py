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
