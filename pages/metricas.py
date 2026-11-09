import csv
import io
from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from db.database import init_db
from services.metricas import (
    AMOSTRA_MINIMA_PERCENTIS,
    comparacao_paralelo_sequencial,
    erros_por_ticker,
    percentis_latencia_api,
    resumo_metricas,
)

init_db()

ROTULOS_CATEGORIA = {
    "acoes": "Ações",
    "renda_fixa": "Renda fixa (CDI/Selic)",
    "todas": "Todas",
}

COLUNAS_LOG = [
    "registrado_em",
    "ticker",
    "categoria",
    "periodo",
    "grupo_fonte",
    "veio_do_cache",
    "sucesso",
    "tempo_resposta_ms",
    "erro",
    "fonte",
]


# =========================
# Helpers
# =========================


def _csv_bytes(linhas, colunas):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, extrasaction="ignore")
    w.writeheader()
    w.writerows(linhas)
    # utf-8-sig: o Excel abre acentos corretamente.
    return buf.getvalue().encode("utf-8-sig")


def _barra(x, y, cores, textos, titulo_y, altura=320):
    fig = go.Figure(
        go.Bar(
            x=x,
            y=y,
            marker_color=cores,
            text=textos,
            textposition="outside",
        )
    )
    fig.update_layout(
        yaxis_title=titulo_y,
        height=altura,
        margin=dict(t=20, b=30),
        showlegend=False,
    )
    return fig


# =========================
# Página
# =========================


def render_metricas():
    st.title("🧪 Métricas técnicas")

    st.caption(
        "Indicadores de desempenho e qualidade coletados automaticamente a "
        "cada consulta às fontes externas (Dashboard, Carteiras e "
        "Recomendações), usados como base para os resultados do TCC."
    )

    # =========================
    # Filtros
    # =========================

    f1, f2, f3 = st.columns([1, 1, 2])

    with f1:
        categoria = st.selectbox(
            "Categoria",
            options=list(ROTULOS_CATEGORIA),
            format_func=lambda c: ROTULOS_CATEGORIA[c],
            help=(
                "Ações: consultas a cotações (brapi/yfinance, tratadas em "
                "conjunto como 'fonte externa'). Renda fixa: consultas ao "
                "BCB para CDI/Selic."
            ),
        )

    with f2:
        por_data = st.checkbox(
            "Definir período por data",
            value=False,
            help=(
                "Útil para isolar regimes de coleta distintos, por exemplo "
                "antes e depois do bloqueio de ranges da brapi (29/10/2026)."
            ),
        )

    dias = 7
    data_inicio = None
    data_fim = None

    with f3:
        if por_data:
            d1, d2 = st.columns(2)
            data_inicio = d1.date_input(
                "De", value=date.today() - timedelta(days=7), key="met_ini"
            )
            data_fim = d2.date_input(
                "Até (inclusive)", value=date.today(), key="met_fim"
            )

            if data_inicio > data_fim:
                st.error("A data inicial não pode ser posterior à data final.")
                return
        else:
            dias = st.selectbox(
                "Janela de análise",
                options=[1, 7, 15, 30],
                index=1,
                format_func=lambda d: f"Últimos {d} dia(s)",
            )

    janela = dict(dias=dias, data_inicio=data_inicio, data_fim=data_fim)

    resumo = resumo_metricas(categoria=categoria, **janela)

    if resumo["total"] == 0:
        st.info(
            "Ainda não há requisições registradas para este filtro. "
            "Navegue pelo Dashboard ou pelas Carteiras para gerar dados, "
            "ou amplie o período."
        )
        return

    # =========================
    # KPIs principais
    # =========================

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total de requisições", resumo["total"])

    col2.metric("Taxa de cache hit", f"{resumo['taxa_cache_hit']:.1f}%")

    col3.metric(
        "Tempo médio (fonte externa)",
        f"{resumo['tempo_medio_api_ms']:.0f} ms",
    )

    col4.metric(
        "Taxa de erro",
        f"{resumo['taxa_erro']:.1f}%",
        delta=f"{resumo['total_erros']} erro(s)",
        delta_color="inverse",
    )

    st.caption(
        "A taxa de erro é medida por tentativa: se a fonte primária falha e "
        "o fallback atende, o log registra uma falha e um sucesso."
    )

    st.divider()

    # =========================
    # Percentis de latência
    # =========================

    st.subheader("Distribuição da latência da fonte externa (percentis)")

    st.caption(
        "A média pode ser distorcida por picos isolados de latência. Os "
        "percentis mostram o comportamento típico (p50) e a cauda da "
        "distribuição (p90/p95/p99)."
    )

    percentis = percentis_latencia_api(categoria=categoria, **janela)

    if percentis["amostras"] == 0:
        st.caption(
            "Nenhuma chamada real à fonte externa neste filtro para calcular percentis."
        )
    else:
        st.caption(f"Baseado em {percentis['amostras']} chamada(s) real(is).")

        if percentis["amostra_pequena"]:
            st.warning(
                f"Amostra pequena (N < {AMOSTRA_MINIMA_PERCENTIS}): p95 e p99 "
                "são interpolados de poucas chamadas e devem ser lidos com cautela."
            )

        rotulos = ["Mín", "p50", "p90", "p95", "p99", "Máx"]
        valores = [
            percentis["min_ms"],
            percentis["p50_ms"],
            percentis["p90_ms"],
            percentis["p95_ms"],
            percentis["p99_ms"],
            percentis["max_ms"],
        ]

        for coluna, rotulo, valor in zip(st.columns(6), rotulos, valores):
            coluna.metric(rotulo, f"{valor:.0f} ms")

        st.plotly_chart(
            _barra(
                rotulos,
                valores,
                "#3498db",
                [f"{v:.0f} ms" for v in valores],
                "Tempo de resposta (ms)",
            ),
            use_container_width=True,
        )

    st.divider()

    # =========================
    # Cache vs. fonte externa
    # =========================

    st.subheader("Cache vs. fonte externa — economia de desempenho")

    st.caption(
        "Compara o tempo de resposta servido pelo cache local com o de uma "
        "chamada real à fonte externa, estimando o ganho de desempenho e o "
        "volume de acessos externos evitados."
    )

    tem_cache = resumo["tempo_medio_cache_ms"] > 0
    tem_api = resumo["tempo_medio_api_ms"] > 0

    if not (tem_cache and tem_api):
        st.caption(
            "Ainda não há amostras suficientes de cache e de fonte externa "
            "neste filtro. Navegue pelo sistema até gerar os dois tipos de resposta."
        )
    else:
        cc1, cc2, cc3, cc4 = st.columns(4)

        cc1.metric("Tempo médio — Cache", f"{resumo['tempo_medio_cache_ms']:.1f} ms")
        cc2.metric(
            "Tempo médio — Fonte externa", f"{resumo['tempo_medio_api_ms']:.0f} ms"
        )
        cc3.metric(
            "Redução de tempo com cache",
            f"{resumo['reducao_tempo_pct']:.1f}%",
        )
        cc4.metric(
            "Chamadas evitadas",
            resumo["chamadas_evitadas"],
            delta=f"~{resumo['tempo_total_economizado_ms'] / 1000:.2f} s economizados",
        )

        st.plotly_chart(
            _barra(
                ["Cache", "Fonte externa"],
                [resumo["tempo_medio_cache_ms"], resumo["tempo_medio_api_ms"]],
                ["#2ecc71", "#3498db"],
                [
                    f"{resumo['tempo_medio_cache_ms']:.1f} ms",
                    f"{resumo['tempo_medio_api_ms']:.0f} ms",
                ],
                "Tempo médio de resposta (ms)",
            ),
            use_container_width=True,
        )

    st.divider()

    # =========================
    # Paralelo vs. sequencial
    # =========================

    st.subheader("Paralelo vs. sequencial — busca em lote")

    st.caption(
        "Compara o tempo total de busca de múltiplos ativos em modo paralelo "
        "(ThreadPoolExecutor) contra o modo sequencial (baseline), medido no "
        "Dashboard pela opção 'Modo sequencial (baseline)'. Esta comparação "
        "envolve apenas ações."
    )

    todos_lotes = comparacao_paralelo_sequencial(**janela)
    tamanhos = sorted({r["qtd_tickers"] for r in todos_lotes["linhas"]})

    qtd_filtro = None
    if tamanhos:
        escolha = st.selectbox(
            "Tamanho do lote (nº de ativos)",
            options=["Todos"] + tamanhos,
            help=(
                "Comparar lotes do mesmo tamanho evita misturar buscas de "
                "2 ativos com buscas de 8. Para uma comparação limpa, rode "
                "os dois modos com cache frio."
            ),
        )
        qtd_filtro = None if escolha == "Todos" else escolha

    comp_par = comparacao_paralelo_sequencial(qtd_tickers=qtd_filtro, **janela)

    tem_paralelo = comp_par["total_paralelo"] > 0
    tem_sequencial = comp_par["total_sequencial"] > 0

    if not (tem_paralelo and tem_sequencial):
        st.caption(
            "Ainda não há amostras dos dois modos neste filtro. No Dashboard, "
            "busque ativos com e sem o 'Modo sequencial' marcado para gerar o comparativo."
        )
    else:
        pp1, pp2, pp3, pp4 = st.columns(4)

        pp1.metric(
            "Tempo médio — Paralelo",
            f"{comp_par['tempo_medio_paralelo_ms']:.0f} ms",
        )
        pp2.metric(
            "Tempo médio — Sequencial",
            f"{comp_par['tempo_medio_sequencial_ms']:.0f} ms",
        )
        pp3.metric("Ganho de velocidade", f"{comp_par['fator_speedup']:.2f}x")
        pp4.metric(
            "Amostras (par. / seq.)",
            f"{comp_par['total_paralelo']} / {comp_par['total_sequencial']}",
        )

        st.plotly_chart(
            _barra(
                ["Paralelo", "Sequencial"],
                [
                    comp_par["tempo_medio_paralelo_ms"],
                    comp_par["tempo_medio_sequencial_ms"],
                ],
                ["#9b59b6", "#e67e22"],
                [
                    f"{comp_par['tempo_medio_paralelo_ms']:.0f} ms",
                    f"{comp_par['tempo_medio_sequencial_ms']:.0f} ms",
                ],
                "Tempo total médio de busca em lote (ms)",
            ),
            use_container_width=True,
        )

        st.caption(
            f"Em média, cada busca paralela cobriu "
            f"{comp_par['media_tickers_paralelo']:.1f} ativo(s), contra "
            f"{comp_par['media_tickers_sequencial']:.1f} no modo sequencial."
        )

        if qtd_filtro is None and (
            round(comp_par["media_tickers_paralelo"], 1)
            != round(comp_par["media_tickers_sequencial"], 1)
        ):
            st.warning(
                "Os dois modos cobriram, em média, números diferentes de ativos. "
                "Filtre por tamanho de lote para uma comparação justa."
            )

    st.divider()

    # =========================
    # Erros por ticker
    # =========================

    erros = erros_por_ticker(categoria=categoria, **janela)

    if erros:
        with st.expander(f"Erros por ticker ({len(erros)})"):
            st.dataframe(erros, use_container_width=True, hide_index=True)

    # =========================
    # Log detalhado + exportação
    # =========================

    with st.expander("Ver log detalhado das requisições"):
        st.dataframe(
            resumo["linhas"],
            column_order=COLUNAS_LOG,
            use_container_width=True,
            hide_index=True,
        )

    st.download_button(
        "⬇️ Baixar log filtrado (CSV)",
        data=_csv_bytes(resumo["linhas"], COLUNAS_LOG),
        file_name=f"log_requisicoes_{categoria}.csv",
        mime="text/csv",
    )


# =========================
# Execução da página
# =========================

usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar as métricas.")
    st.stop()

render_metricas()
