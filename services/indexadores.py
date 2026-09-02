import time
from datetime import date, datetime, timedelta, timezone

import requests

from db.database import get_connection

CODIGOS_SGS = {
    "CDI": 12,
    "SELIC": 11,
}


def _chamar_bcb(codigo_serie, data_inicial, data_final):
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados"
        f"?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"
    )
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def _registrar_log(indexador, referencia, veio_do_cache, sucesso, tempo_resposta_ms, erro=None):
    """
    Reaproveita a tabela log_requisicoes para que as chamadas ao CDI/Selic
    também apareçam nas Métricas técnicas do TCC. O "ticker" é registrado
    entre colchetes (ex.: "[CDI]") para diferenciar de ações no log.
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
            f"[{indexador}]",
            referencia,
            1 if veio_do_cache else 0,
            1 if sucesso else 0,
            tempo_resposta_ms,
            erro,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def rendimento_desde(indexador, data_inicio_iso, percentual_indexador=100.0, ttl_minutos=15):
    """
    Calcula o rendimento percentual acumulado do indexador (CDI ou SELIC)
    entre `data_inicio_iso` (formato "AAAA-MM-DD", data do aporte) e hoje.

    O percentual contratado (ex.: 100% do CDI, 110% do CDI) é aplicado
    sobre o fator acumulado do período (fator ** (percentual / 100)) —
    aproximação padrão de mercado para prazos de meses/anos, suficiente
    para os fins de estimativa do TCC.
    """
    data_inicio = datetime.fromisoformat(data_inicio_iso).date()
    hoje = date.today()

    if data_inicio >= hoje:
        return 0.0

    chave = f"{indexador}:{data_inicio.isoformat()}:{hoje.isoformat()}"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT valor_acumulado, coletado_em FROM cache_indexadores WHERE chave = ?",
        (chave,),
    )
    row = cur.fetchone()

    if row is not None:
        coletado_em = datetime.fromisoformat(row["coletado_em"])
        if datetime.now(timezone.utc) - coletado_em < timedelta(minutes=ttl_minutos):
            conn.close()
            _registrar_log(indexador, chave, True, True, 0.0)
            fator = row["valor_acumulado"]
            return (fator ** (percentual_indexador / 100) - 1) * 100

    codigo_serie = CODIGOS_SGS.get(indexador)
    if codigo_serie is None:
        conn.close()
        raise ValueError(f"Indexador desconhecido: {indexador}")

    inicio_str = data_inicio.strftime("%d/%m/%Y")
    fim_str = hoje.strftime("%d/%m/%Y")

    t0 = time.perf_counter()
    try:
        dados = _chamar_bcb(codigo_serie, inicio_str, fim_str)
    except Exception as e:
        tempo_ms = (time.perf_counter() - t0) * 1000
        conn.close()
        _registrar_log(indexador, chave, False, False, tempo_ms, str(e))
        raise

    tempo_ms = (time.perf_counter() - t0) * 1000

    fator = 1.0
    for ponto in dados:
        try:
            taxa_dia = float(str(ponto["valor"]).replace(",", "."))
        except (KeyError, ValueError, TypeError):
            continue
        fator *= 1 + taxa_dia / 100

    cur.execute(
        """
        INSERT INTO cache_indexadores (chave, valor_acumulado, coletado_em)
        VALUES (?, ?, ?)
        ON CONFLICT(chave) DO UPDATE SET
            valor_acumulado = excluded.valor_acumulado,
            coletado_em = excluded.coletado_em
        """,
        (chave, fator, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    _registrar_log(indexador, chave, False, True, tempo_ms)

    return (fator ** (percentual_indexador / 100) - 1) * 100
