from datetime import datetime, timezone

from db.database import get_connection


# =========================
# Carteiras
# =========================


def criar_carteira(usuario_id, nome):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO carteiras (usuario_id, nome, criada_em) VALUES (?, ?, ?)",
        (usuario_id, nome.strip(), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    carteira_id = cur.lastrowid
    conn.close()
    return carteira_id


def listar_carteiras(usuario_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM carteiras WHERE usuario_id = ? ORDER BY criada_em", (usuario_id,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def excluir_carteira(carteira_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM carteiras WHERE id = ?", (carteira_id,))
    conn.commit()
    conn.close()


# =========================
# Operações (compra/venda)
# =========================


def registrar_operacao(carteira_id, ticker, tipo, quantidade, preco, data_operacao):
    """
    Registra uma operação de compra ou venda.
    `data_operacao` no formato ISO (ex: "2026-09-01").
    Para venda, valida que não excede a posição atual.
    """
    if tipo not in ("compra", "venda"):
        raise ValueError("tipo deve ser 'compra' ou 'venda'")

    if quantidade <= 0 or preco <= 0:
        raise ValueError("quantidade e preço devem ser maiores que zero")

    if tipo == "venda":
        posicao_atual = _quantidade_atual(carteira_id, ticker)
        if quantidade > posicao_atual:
            raise ValueError(
                f"Quantidade insuficiente: você tem {posicao_atual} de {ticker}, "
                f"tentou vender {quantidade}."
            )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO operacoes
            (carteira_id, ticker, tipo, quantidade, preco, data_operacao, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            carteira_id,
            ticker,
            tipo,
            quantidade,
            preco,
            data_operacao,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    operacao_id = cur.lastrowid
    conn.close()
    return operacao_id


def listar_operacoes(carteira_id, ticker=None):
    conn = get_connection()
    cur = conn.cursor()
    if ticker:
        cur.execute(
            """
            SELECT * FROM operacoes
            WHERE carteira_id = ? AND ticker = ?
            ORDER BY data_operacao, id
            """,
            (carteira_id, ticker),
        )
    else:
        cur.execute(
            "SELECT * FROM operacoes WHERE carteira_id = ? ORDER BY data_operacao, id",
            (carteira_id,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def remover_operacao(operacao_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM operacoes WHERE id = ?", (operacao_id,))
    conn.commit()
    conn.close()


def _quantidade_atual(carteira_id, ticker):
    operacoes = listar_operacoes(carteira_id, ticker)
    qtd = 0.0
    for op in operacoes:
        if op["tipo"] == "compra":
            qtd += op["quantidade"]
        else:
            qtd -= op["quantidade"]
    return qtd


# =========================
# Cálculo de posições consolidadas
# =========================


def calcular_posicoes(carteira_id):
    """
    Processa o histórico de operações e retorna, para cada ticker com
    posição em aberto (quantidade > 0): quantidade, preço médio e custo total.
    """
    operacoes = listar_operacoes(carteira_id)

    posicoes = {}

    for op in operacoes:
        ticker = op["ticker"]

        if ticker not in posicoes:
            posicoes[ticker] = {"quantidade": 0.0, "preco_medio": 0.0}

        pos = posicoes[ticker]

        if op["tipo"] == "compra":
            custo_atual = pos["quantidade"] * pos["preco_medio"]
            custo_novo = op["quantidade"] * op["preco"]
            nova_quantidade = pos["quantidade"] + op["quantidade"]

            pos["preco_medio"] = (
                (custo_atual + custo_novo) / nova_quantidade
                if nova_quantidade > 0
                else 0.0
            )
            pos["quantidade"] = nova_quantidade
        else:
            pos["quantidade"] -= op["quantidade"]

    resultado = []
    for ticker, pos in posicoes.items():
        if pos["quantidade"] > 0:
            resultado.append(
                {
                    "ticker": ticker,
                    "quantidade": pos["quantidade"],
                    "preco_medio": pos["preco_medio"],
                    "custo_total": pos["quantidade"] * pos["preco_medio"],
                }
            )

    return resultado
