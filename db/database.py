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

    # =========================
    # Operações (compra/venda) — ações da B3
    # =========================
    # Cada linha representa uma operação individual de compra ou venda.
    # Quantidade, preço médio e P/L são derivados a partir daqui
    # (services.carteira.calcular_posicoes), nunca armazenados prontos.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carteira_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('compra', 'venda')),
            quantidade REAL NOT NULL,
            preco REAL NOT NULL,
            data_operacao TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (carteira_id) REFERENCES carteiras(id) ON DELETE CASCADE
        )
    """)

    # =========================
    # Aportes em Renda Fixa (CDI/Selic)
    # =========================
    # Cada linha representa um aporte em um indexador (CDI ou SELIC) a um
    # certo percentual contratado (ex.: 100%, 110%). O rendimento é
    # calculado a partir da data do aporte até hoje
    # (services.renda_fixa.calcular_posicoes), usando as séries diárias
    # do Banco Central. Não há suporte a resgate parcial nesta versão —
    # cada aporte é uma posição independente até ser removido.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aportes_renda_fixa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carteira_id INTEGER NOT NULL,
            indexador TEXT NOT NULL CHECK (indexador IN ('CDI', 'SELIC')),
            percentual_indexador REAL NOT NULL,
            valor REAL NOT NULL,
            data_operacao TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (carteira_id) REFERENCES carteiras(id) ON DELETE CASCADE
        )
    """)

    # =========================
    # Cache de indexadores (CDI/Selic) — séries diárias do BCB
    # =========================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cache_indexadores (
            chave TEXT PRIMARY KEY,
            valor_acumulado REAL NOT NULL,
            coletado_em TEXT NOT NULL
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
    # Registra cada consulta feita via services.cache.buscar_ativo e
    # services.indexadores.rendimento_desde, seja ela servida pelo cache
    # local ou pela API externa (brapi.dev ou BCB/SGS). Usado para
    # calcular taxa de cache hit, tempo médio de resposta e taxa de erro —
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
