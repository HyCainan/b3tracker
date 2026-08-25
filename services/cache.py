import json
from datetime import datetime, timedelta

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


def buscar_ativo(ticker, periodo, token, ttl_minutos=15):
    """
    Busca a cotação de um ticker respeitando o cache local com TTL.
    Retorna (dados, veio_do_cache).
    A chave de cache combina ticker + período pois o histórico varia por período.
    """
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
            conn.close()
            return json.loads(row["dados_json"]), True

    dados = _chamar_api(ticker, periodo, token)

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
    return dados, False
