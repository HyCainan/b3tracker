from datetime import datetime

from db.database import get_connection


def criar_carteira(usuario_id, nome):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO carteiras (usuario_id, nome, criada_em) VALUES (?, ?, ?)",
        (usuario_id, nome.strip(), datetime.utcnow().isoformat()),
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


def adicionar_ativo(carteira_id, ticker, valor_alocado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO carteira_ativos (carteira_id, ticker, valor_alocado, adicionado_em)
        VALUES (?, ?, ?, ?)
        """,
        (carteira_id, ticker, valor_alocado, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def listar_ativos(carteira_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM carteira_ativos WHERE carteira_id = ? ORDER BY adicionado_em",
        (carteira_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def remover_ativo(ativo_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM carteira_ativos WHERE id = ?", (ativo_id,))
    conn.commit()
    conn.close()
