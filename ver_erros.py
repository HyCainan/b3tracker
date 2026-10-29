from db.database import get_connection

conn = get_connection()

print("== Resumo por fonte (hoje) ==")
for r in conn.execute("""
    SELECT fonte, sucesso, COUNT(*) AS n
    FROM log_requisicoes
    WHERE registrado_em >= '2026-10-29'
    GROUP BY fonte, sucesso
"""):
    print(dict(r))

print("\n== Falhas (hoje) ==")
for r in conn.execute("""
    SELECT ticker, periodo, fonte, tempo_resposta_ms, erro, registrado_em
    FROM log_requisicoes
    WHERE sucesso = 0 AND registrado_em >= '2026-10-29'
    ORDER BY registrado_em DESC
    LIMIT 30
"""):
    print(dict(r))

print("\n== Colunas da tabela ==")
print([c["name"] for c in conn.execute("PRAGMA table_info(log_requisicoes)")])
conn.close()
