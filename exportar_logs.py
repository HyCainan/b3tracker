"""
Exporta os logs de desempenho do B3Tracker para CSV (insumo do Capítulo 6).

Uso (na raiz do projeto, onde estão app.py e db/):
    python exportar_logs.py

Gera a pasta export_tcc/ com:
    log_requisicoes.csv   -> todas as requisições (com colunas derivadas)
    log_buscas_lote.csv   -> buscas em lote (paralelo x sequencial)
    resumo.txt            -> contagens, períodos e ambiente de execução

Não exporta usuários, senhas, carteiras nem operações.
"""

import csv
import os
import platform
import sys
from importlib import metadata

from db.database import get_connection

PASTA = "export_tcc"


def exportar_tabela(conn, sql, caminho):
    cur = conn.execute(sql)
    colunas = [c[0] for c in cur.description]
    linhas = cur.fetchall()

    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(colunas)
        for r in linhas:
            w.writerow([r[c] for c in colunas])

    return len(linhas)


def versao(pacote):
    try:
        return metadata.version(pacote)
    except metadata.PackageNotFoundError:
        return "não instalado"


def main():
    os.makedirs(PASTA, exist_ok=True)
    conn = get_connection()

    # ------------------------------------------------------------------
    # log_requisicoes (+ colunas derivadas)
    #   categoria: renda_fixa quando o ticker vem entre colchetes ([CDI]...)
    #   origem:    cache | api
    #   fonte:     coluna original; nulos tratados como brapi/bcb
    # ------------------------------------------------------------------
    n_req = exportar_tabela(
        conn,
        """
        SELECT
            id,
            ticker,
            periodo,
            veio_do_cache,
            sucesso,
            tempo_resposta_ms,
            erro,
            registrado_em,
            fonte,
            CASE WHEN ticker LIKE '[%' THEN 'renda_fixa' ELSE 'acao' END AS categoria,
            CASE WHEN veio_do_cache = 1 THEN 'cache' ELSE 'api' END AS origem,
            COALESCE(
                fonte,
                CASE WHEN ticker LIKE '[%' THEN 'bcb' ELSE 'brapi' END
            ) AS fonte_efetiva
        FROM log_requisicoes
        ORDER BY registrado_em
        """,
        os.path.join(PASTA, "log_requisicoes.csv"),
    )

    n_lote = exportar_tabela(
        conn,
        "SELECT * FROM log_buscas_lote ORDER BY registrado_em",
        os.path.join(PASTA, "log_buscas_lote.csv"),
    )

    # ------------------------------------------------------------------
    # resumo.txt
    # ------------------------------------------------------------------
    linhas = []
    linhas.append("== Volume ==")
    linhas.append(f"log_requisicoes: {n_req} linhas")
    linhas.append(f"log_buscas_lote: {n_lote} linhas")

    linhas.append("\n== Período coberto (UTC) ==")
    for tabela in ("log_requisicoes", "log_buscas_lote"):
        r = conn.execute(
            f"SELECT MIN(registrado_em) AS ini, MAX(registrado_em) AS fim FROM {tabela}"
        ).fetchone()
        linhas.append(f"{tabela}: {r['ini']}  ->  {r['fim']}")

    linhas.append("\n== log_requisicoes por categoria / fonte / origem / sucesso ==")
    for r in conn.execute(
        """
        SELECT
            CASE WHEN ticker LIKE '[%' THEN 'renda_fixa' ELSE 'acao' END AS categoria,
            COALESCE(fonte, CASE WHEN ticker LIKE '[%' THEN 'bcb' ELSE 'brapi' END) AS fonte,
            CASE WHEN veio_do_cache = 1 THEN 'cache' ELSE 'api' END AS origem,
            sucesso,
            COUNT(*) AS n
        FROM log_requisicoes
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
        """
    ):
        linhas.append(dict(r).__repr__())

    linhas.append("\n== log_requisicoes por período (somente ações) ==")
    for r in conn.execute(
        """
        SELECT periodo, COUNT(*) AS n
        FROM log_requisicoes
        WHERE ticker NOT LIKE '[%'
        GROUP BY periodo
        ORDER BY n DESC
        """
    ):
        linhas.append(dict(r).__repr__())

    linhas.append("\n== log_buscas_lote por modo e nº de tickers ==")
    for r in conn.execute(
        """
        SELECT modo, qtd_tickers, COUNT(*) AS n,
               ROUND(AVG(tempo_total_ms), 1) AS media_ms
        FROM log_buscas_lote
        GROUP BY modo, qtd_tickers
        ORDER BY modo, qtd_tickers
        """
    ):
        linhas.append(dict(r).__repr__())

    linhas.append("\n== Ambiente de execução ==")
    linhas.append(f"SO: {platform.platform()}")
    linhas.append(f"Processador: {platform.processor() or 'n/d'}")
    linhas.append(f"Núcleos lógicos: {os.cpu_count()}")
    linhas.append(f"Python: {sys.version.split()[0]}")
    for pkg in ("streamlit", "requests", "yfinance", "plotly", "bcrypt"):
        linhas.append(f"{pkg}: {versao(pkg)}")

    conn.close()

    with open(os.path.join(PASTA, "resumo.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")

    print(f"Exportação concluída em ./{PASTA}/")
    print(f"  log_requisicoes.csv ({n_req} linhas)")
    print(f"  log_buscas_lote.csv ({n_lote} linhas)")
    print("  resumo.txt")


if __name__ == "__main__":
    main()
