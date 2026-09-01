import os
import sqlite3

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "b3tracker.db",
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Cria as tabelas do sistema caso ainda não existam."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS carteiras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            criada_em TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS carteira_ativos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carteira_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            valor_alocado REAL NOT NULL,
            adicionado_em TEXT NOT NULL,
            FOREIGN KEY (carteira_id) REFERENCES carteiras(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cache_cotacoes (
            ticker TEXT PRIMARY KEY,
            dados_json TEXT NOT NULL,
            coletado_em TEXT NOT NULL
        )
    """)

    # =========================
    # Log de requisições (métricas técnicas)
    # =========================
    # Registra cada consulta feita via services.cache.buscar_ativo, seja ela
    # servida pelo cache local ou pela API da brapi.dev. Usado para calcular
    # taxa de cache hit, tempo médio de resposta da API e taxa de erro —
    # métricas de desempenho e qualidade de dados apresentadas no TCC.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS log_requisicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            periodo TEXT NOT NULL,
            veio_do_cache INTEGER NOT NULL,
            sucesso INTEGER NOT NULL,
            tempo_resposta_ms REAL,
            erro TEXT,
            registrado_em TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
