import sqlite3
from datetime import datetime, timezone

import bcrypt

from db.database import get_connection


def criar_usuario(nome, email, senha):
    conn = get_connection()
    cur = conn.cursor()

    email = email.strip().lower()
    senha_hash = bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha_hash, criado_em) VALUES (?, ?, ?, ?)",
            (nome.strip(), email, senha_hash, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return {"ok": True, "usuario_id": cur.lastrowid}
    except sqlite3.IntegrityError:
        return {"ok": False, "erro": "Já existe uma conta com este e-mail."}
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao criar usuário: {e}"}
    finally:
        conn.close()


def autenticar_usuario(email, senha):
    conn = get_connection()
    cur = conn.cursor()

    email = email.strip().lower()
    cur.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return {"ok": False, "erro": "E-mail ou senha inválidos."}

    if not bcrypt.checkpw(senha.encode("utf-8"), row["senha_hash"].encode("utf-8")):
        return {"ok": False, "erro": "E-mail ou senha inválidos."}

    return {
        "ok": True,
        "usuario": {"id": row["id"], "nome": row["nome"], "email": row["email"]},
    }


def buscar_usuario_por_id(usuario_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, email FROM usuarios WHERE id = ?", (usuario_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None
