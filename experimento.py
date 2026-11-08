"""
Experimento controlado do TCC (Capítulo 6).

Mede, em condições controladas:
  1. paralelo x sequencial   -> tempo total de busca em lote, com cache frio
  2. cache frio x cache quente -> ganho do cache local sobre a fonte externa

Procedimento de cada rodada (para cada modo, alternando qual vai primeiro):
  a) limpa o cache de cotações
  b) busca o lote completo               -> cenário "frio"
  c) repete imediatamente o mesmo lote   -> cenário "quente"

A ordem dos modos alterna entre as rodadas (ímpar: paralelo primeiro; par:
sequencial primeiro) para que variações de rede ao longo do tempo não
favoreçam sempre o mesmo modo.

O experimento usa um banco SEPARADO (experimento_tcc/<data-hora>/experimento.db),
então não contamina os logs de uso normal da aplicação (b3tracker.db).

Uso (na raiz do projeto, com o .env contendo BRAPI_TOKEN):
    python experimento.py
    python experimento.py --rodadas 20 --periodo 1mo --pausa 2
    python experimento.py --workers 4      # outra configuração do modo paralelo
    (sem --workers: núcleos lógicos - 1)

Saída (pasta experimento_tcc/<data-hora>/):
    rodadas.csv            -> uma linha por execução de lote
    log_buscas_lote.csv    -> log de lote gravado pela própria aplicação
    log_requisicoes.csv    -> log de cada requisição (inclui fonte e erros)
    resumo.txt             -> estatísticas descritivas e ambiente
"""

import argparse
import csv
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib import metadata

from dotenv import load_dotenv

import db.database as database

COLUNAS_RODADAS = [
    "rodada",
    "ordem",
    "modo",
    "workers",
    "cenario",
    "qtd_tickers",
    "tempo_ms",
    "cache_hits",
    "erros",
    "registrado_em",
]


def parse_args():
    p = argparse.ArgumentParser(description="Experimento controlado do B3Tracker")
    p.add_argument("--rodadas", type=int, default=20, help="nº de rodadas (padrão 20)")
    p.add_argument("--periodo", default="1mo", help="período das cotações (padrão 1mo)")
    p.add_argument(
        "--tickers",
        default=None,
        help="lista separada por vírgula; padrão: todos os ativos disponíveis",
    )
    p.add_argument(
        "--pausa",
        type=float,
        default=2.0,
        help="segundos de pausa entre execuções, para aliviar limites de taxa",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="threads do modo paralelo (padrão: núcleos lógicos - 1, como no sistema)",
    )
    p.add_argument("--saida", default="experimento_tcc", help="pasta base de saída")
    return p.parse_args()


def limpar_cache():
    conn = database.get_connection()
    conn.execute("DELETE FROM cache_cotacoes")
    conn.commit()
    conn.close()


def exportar_tabela(sql, caminho):
    conn = database.get_connection()
    cur = conn.execute(sql)
    colunas = [c[0] for c in cur.description]
    linhas = cur.fetchall()
    conn.close()

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


def resumir(valores):
    """Estatísticas descritivas de uma lista de tempos (ms)."""
    if not valores:
        return "n=0"
    dp = statistics.stdev(valores) if len(valores) > 1 else 0.0
    return (
        f"n={len(valores)}  mediana={statistics.median(valores):.0f}  "
        f"média={statistics.mean(valores):.0f}  dp={dp:.0f}  "
        f"mín={min(valores):.0f}  máx={max(valores):.0f}"
    )


def lote_valido(r):
    """
    Execução utilizável para comparar tempos:
      frio   -> nenhum ticker veio do cache e nenhum terminou em erro
      quente -> todos os tickers vieram do cache (lote totalmente servido pelo cache)
    """
    if r["cenario"] == "frio":
        return r["erros"] == 0 and r["cache_hits"] == 0
    return r["cache_hits"] == r["qtd_tickers"]


def montar_resumo(linhas_rodadas, args, tickers):
    saida = []
    saida.append("== Configuração ==")
    saida.append(
        f"rodadas: {args.rodadas}  período: {args.periodo}  "
        f"workers (paralelo): {args.workers} de {os.cpu_count()} núcleos lógicos  pausa: {args.pausa}s"
    )
    saida.append(f"tickers ({len(tickers)}): {', '.join(tickers)}")

    saida.append("\n== Tempo total do lote (ms), somente execuções válidas ==")
    saida.append("(frio = sem cache e sem erros; quente = 100% servido pelo cache)")
    for cenario in ("frio", "quente"):
        for modo in ("paralelo", "sequencial"):
            todas = [
                r
                for r in linhas_rodadas
                if r["modo"] == modo and r["cenario"] == cenario
            ]
            vals = [r["tempo_ms"] for r in todas if lote_valido(r)]
            saida.append(
                f"{cenario:6s} {modo:10s} {resumir(vals)}  (válidas {len(vals)} de {len(todas)})"
            )

    saida.append("\n== Lotes completos por modo (cache frio) ==")
    for modo in ("paralelo", "sequencial"):
        frios = [
            r for r in linhas_rodadas if r["modo"] == modo and r["cenario"] == "frio"
        ]
        if frios:
            completos = sum(1 for r in frios if r["erros"] == 0)
            erros_tot = sum(r["erros"] for r in frios)
            saida.append(
                f"{modo:10s} lotes sem erro: {completos}/{len(frios)}  "
                f"tickers com erro (soma): {erros_tot}"
            )

    # Speedup pareado por rodada (cache frio, ambos válidos)
    por_rodada = {}
    for r in linhas_rodadas:
        if r["cenario"] == "frio" and lote_valido(r):
            por_rodada.setdefault(r["rodada"], {})[r["modo"]] = r["tempo_ms"]

    razoes = [
        d["sequencial"] / d["paralelo"]
        for d in por_rodada.values()
        if "sequencial" in d and "paralelo" in d and d["paralelo"] > 0
    ]
    saida.append("\n== Speedup pareado (sequencial / paralelo, cache frio) ==")
    if razoes:
        saida.append(
            f"rodadas pareadas={len(razoes)}  mediana={statistics.median(razoes):.2f}x  "
            f"média={statistics.mean(razoes):.2f}x  mín={min(razoes):.2f}x  máx={max(razoes):.2f}x"
        )
    else:
        saida.append("nenhuma rodada pareada com ambos os modos válidos.")

    # Ganho do cache pareado (frio / quente, mesmo modo e rodada)
    saida.append("\n== Ganho do cache (frio / quente, pareado por rodada e modo) ==")
    for modo in ("paralelo", "sequencial"):
        pares = {}
        for r in linhas_rodadas:
            if r["modo"] == modo and lote_valido(r):
                pares.setdefault(r["rodada"], {})[r["cenario"]] = r["tempo_ms"]
        raz = [
            d["frio"] / d["quente"]
            for d in pares.values()
            if "frio" in d and "quente" in d and d["quente"] > 0
        ]
        if raz:
            saida.append(
                f"{modo:10s} pares={len(raz)}  mediana={statistics.median(raz):.1f}x  "
                f"média={statistics.mean(raz):.1f}x"
            )
        else:
            saida.append(f"{modo:10s} sem pares válidos.")

    saida.append("\n== Execuções com erro ==")
    com_erro = [r for r in linhas_rodadas if r["erros"] > 0]
    saida.append(
        f"{len(com_erro)} de {len(linhas_rodadas)} execuções tiveram ao menos um ticker sem dados."
    )

    saida.append("\n== Ambiente de execução ==")
    saida.append(f"SO: {platform.platform()}")
    saida.append(f"Processador: {platform.processor() or 'n/d'}")
    saida.append(f"Núcleos lógicos: {os.cpu_count()}")
    saida.append(f"Python: {sys.version.split()[0]}")
    for pkg in ("streamlit", "requests", "yfinance", "plotly", "bcrypt"):
        saida.append(f"{pkg}: {versao(pkg)}")

    return "\n".join(saida) + "\n"


def main():
    args = parse_args()
    load_dotenv()
    token = os.getenv("BRAPI_TOKEN")
    if not token:
        print("BRAPI_TOKEN não encontrado no .env.")
        sys.exit(1)

    # Pasta e banco exclusivos desta execução do experimento.
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    pasta = os.path.join(args.saida, carimbo)
    os.makedirs(pasta, exist_ok=True)

    database.DB_PATH = os.path.abspath(os.path.join(pasta, "experimento.db"))
    database.init_db()

    # Importado depois de apontar o banco para o arquivo do experimento.
    from services.cache import (
        TICKERS_DISPONIVEIS,
        WORKERS_PADRAO,
        buscar_ativos_paralelo,
    )

    if args.workers is None:
        args.workers = WORKERS_PADRAO

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = list(TICKERS_DISPONIVEIS)

    print(
        f"Experimento: {args.rodadas} rodadas, {len(tickers)} ativos, "
        f"período {args.periodo}, workers {args.workers}"
    )
    print(f"Saída: {pasta}\n")

    caminho_rodadas = os.path.join(pasta, "rodadas.csv")
    linhas_rodadas = []

    with open(caminho_rodadas, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=COLUNAS_RODADAS)
        writer.writeheader()

        try:
            for rodada in range(1, args.rodadas + 1):
                # Alterna qual modo executa primeiro.
                modos = [True, False] if rodada % 2 == 1 else [False, True]

                for ordem, paralelo in enumerate(modos, start=1):
                    modo = "paralelo" if paralelo else "sequencial"
                    limpar_cache()

                    for cenario in ("frio", "quente"):
                        t0 = time.perf_counter()
                        respostas = buscar_ativos_paralelo(
                            tickers,
                            args.periodo,
                            token,
                            max_workers=args.workers,
                            paralelo=paralelo,
                            cenario=cenario,
                            rodada=rodada,
                        )
                        tempo_ms = (time.perf_counter() - t0) * 1000

                        cache_hits = sum(1 for _, _, c, _ in respostas if c)
                        erros = sum(1 for _, s, _, e in respostas if e or not s)

                        linha = {
                            "rodada": rodada,
                            "ordem": ordem,
                            "modo": modo,
                            "workers": args.workers if paralelo else 1,
                            "cenario": cenario,
                            "qtd_tickers": len(tickers),
                            "tempo_ms": round(tempo_ms, 1),
                            "cache_hits": cache_hits,
                            "erros": erros,
                            "registrado_em": datetime.now(timezone.utc).isoformat(),
                        }
                        writer.writerow(linha)
                        f_csv.flush()
                        linhas_rodadas.append(linha)

                        print(
                            f"rodada {rodada:>2}/{args.rodadas}  {modo:10s} {cenario:6s} "
                            f"{tempo_ms:8.0f} ms  cache={cache_hits:>2}  erros={erros}"
                        )

                        time.sleep(args.pausa)

        except KeyboardInterrupt:
            print("\nInterrompido pelo usuário; salvando o que foi coletado...")

    # Exporta os logs gravados pela própria aplicação durante o experimento.
    exportar_tabela(
        "SELECT * FROM log_buscas_lote ORDER BY registrado_em",
        os.path.join(pasta, "log_buscas_lote.csv"),
    )
    exportar_tabela(
        """
        SELECT *,
               CASE WHEN veio_do_cache = 1 THEN 'cache' ELSE 'api' END AS origem
        FROM log_requisicoes
        ORDER BY registrado_em
        """,
        os.path.join(pasta, "log_requisicoes.csv"),
    )

    resumo = montar_resumo(linhas_rodadas, args, tickers)
    with open(os.path.join(pasta, "resumo.txt"), "w", encoding="utf-8") as f:
        f.write(resumo)

    print("\n" + resumo)
    print(f"Arquivos salvos em {pasta}")


if __name__ == "__main__":
    main()
