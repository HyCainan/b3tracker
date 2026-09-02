from datetime import datetime, timezone

from db.database import get_connection
from services.indexadores import rendimento_desde


# =========================
# Aportes em Renda Fixa (CDI/Selic)
# =========================


def registrar_aporte(carteira_id, indexador, percentual_indexador, valor, data_operacao):
    """
    Registra um aporte em renda fixa indexado a CDI ou SELIC.
    `data_operacao` no formato ISO (ex: "2026-09-01").

    Não há suporte a resgate parcial nesta versão: cada aporte é uma
    posição independente, que só sai da carteira sendo removida
    (services.renda_fixa.remover_aporte).
    """
    if indexador not in ("CDI", "SELIC"):
        raise ValueError("indexador deve ser 'CDI' ou 'SELIC'")

    if valor <= 0:
        raise ValueError("valor deve ser maior que zero")

    if percentual_indexador <= 0:
        raise ValueError("percentual do indexador deve ser maior que zero")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO aportes_renda_fixa
            (carteira_id, indexador, percentual_indexador, valor, data_operacao, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            carteira_id,
            indexador,
            percentual_indexador,
            valor,
            data_operacao,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    aporte_id = cur.lastrowid
    conn.close()
    return aporte_id


def listar_aportes(carteira_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM aportes_renda_fixa WHERE carteira_id = ? ORDER BY data_operacao, id",
        (carteira_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def remover_aporte(aporte_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM aportes_renda_fixa WHERE id = ?", (aporte_id,))
    conn.commit()
    conn.close()


# =========================
# Cálculo de posições consolidadas
# =========================


def calcular_posicoes(carteira_id):
    """
    Para cada aporte em aberto, calcula o valor atual estimado aplicando
    o rendimento acumulado do indexador (CDI/Selic) desde a data do
    aporte até hoje (services.indexadores.rendimento_desde).
    """
    aportes = listar_aportes(carteira_id)

    posicoes = []

    for aporte in aportes:
        try:
            variacao_pct = rendimento_desde(
                aporte["indexador"],
                aporte["data_operacao"],
                aporte["percentual_indexador"],
            )
            erro = False
        except Exception:
            variacao_pct = 0.0
            erro = True

        valor_atual = aporte["valor"] * (1 + variacao_pct / 100)

        posicoes.append(
            {
                "id": aporte["id"],
                "rotulo": f"{aporte['indexador']} {aporte['percentual_indexador']:.0f}%",
                "indexador": aporte["indexador"],
                "percentual_indexador": aporte["percentual_indexador"],
                "valor_aportado": aporte["valor"],
                "valor_atual": valor_atual,
                "variacao_pct": variacao_pct,
                "data_operacao": aporte["data_operacao"],
                "erro": erro,
            }
        )

    return posicoes
