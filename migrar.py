from db.database import get_connection

conn = get_connection()
cols = [c["name"] for c in conn.execute("PRAGMA table_info(log_requisicoes)")]
print("Antes:", cols)

if "fonte" not in cols:
    conn.execute("ALTER TABLE log_requisicoes ADD COLUMN fonte TEXT")
    conn.execute("""
        UPDATE log_requisicoes
        SET fonte = CASE WHEN ticker LIKE '[%' THEN 'bcb' ELSE 'brapi' END
        WHERE fonte IS NULL
    """)
    conn.commit()

print(
    "Depois:", [c["name"] for c in conn.execute("PRAGMA table_info(log_requisicoes)")]
)
conn.close()
