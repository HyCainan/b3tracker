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
    cur.execute(
        "SELECT id, nome, email, criado_em FROM usuarios WHERE id = ?", (usuario_id,)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def atualizar_nome(usuario_id, novo_nome):
    novo_nome = novo_nome.strip()

    if not novo_nome:
        return {"ok": False, "erro": "O nome não pode ficar vazio."}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE usuarios SET nome = ? WHERE id = ?", (novo_nome, usuario_id)
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao atualizar nome: {e}"}
    finally:
        conn.close()


def atualizar_email(usuario_id, novo_email):
    novo_email = novo_email.strip().lower()

    if not novo_email or "@" not in novo_email:
        return {"ok": False, "erro": "Informe um e-mail válido."}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE usuarios SET email = ? WHERE id = ?", (novo_email, usuario_id)
        )
        conn.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        return {"ok": False, "erro": "Já existe uma conta com este e-mail."}
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao atualizar e-mail: {e}"}
    finally:
        conn.close()


def atualizar_senha(usuario_id, senha_atual, nova_senha):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (usuario_id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "erro": "Usuário não encontrado."}

    if not bcrypt.checkpw(
        senha_atual.encode("utf-8"), row["senha_hash"].encode("utf-8")
    ):
        conn.close()
        return {"ok": False, "erro": "Senha atual incorreta."}

    if len(nova_senha) < 6:
        conn.close()
        return {"ok": False, "erro": "A nova senha deve ter pelo menos 6 caracteres."}

    novo_hash = bcrypt.hashpw(nova_senha.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    try:
        cur.execute(
            "UPDATE usuarios SET senha_hash = ? WHERE id = ?", (novo_hash, usuario_id)
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao atualizar senha: {e}"}
    finally:
        conn.close()


def excluir_usuario(usuario_id, senha):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (usuario_id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "erro": "Usuário não encontrado."}

    if not bcrypt.checkpw(senha.encode("utf-8"), row["senha_hash"].encode("utf-8")):
        conn.close()
        return {"ok": False, "erro": "Senha incorreta."}

    try:
        cur.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao excluir conta: {e}"}
    finally:
        conn.close()
