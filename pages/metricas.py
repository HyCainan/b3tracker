import plotly.graph_objects as go
import streamlit as st

from services.metricas import erros_por_ticker, resumo_metricas


def render_metricas():
    st.title("🛠️ Métricas técnicas")

    st.caption(
        "Indicadores de desempenho e qualidade coletados automaticamente a "
        "cada consulta à API da brapi.dev (Dashboard e Carteiras), usados "
        "como base para os resultados do TCC."
    )

    col_periodo, _ = st.columns([1, 3])

    with col_periodo:
        dias = st.selectbox(
            "Janela de análise",
            options=[1, 7, 15, 30],
            index=1,
            format_func=lambda d: f"Últimos {d} dia(s)",
        )

    resumo = resumo_metricas(dias)

    if resumo["total"] == 0:
        st.info(
            "Ainda não há requisições registradas neste período. "
            "Navegue pelo Dashboard ou pelas Carteiras para gerar dados."
        )
        return

    # =========================
    # KPIs principais
    # =========================

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total de requisições", resumo["total"])

    col2.metric("Taxa de cache hit", f"{resumo['taxa_cache_hit']:.1f}%")

    col3.metric(
        "Tempo médio de resposta (API)",
        f"{resumo['tempo_medio_api_ms']:.0f} ms",
    )

    col4.metric(
        "Taxa de erro",
        f"{resumo['taxa_erro']:.1f}%",
        delta=f"{resumo['total_erros']} erro(s)",
        delta_color="inverse",
    )

    st.divider()

    # =========================
    # Comparativo: Cache vs. API
    # =========================

    st.subheader("⚡ Cache vs. API — economia de desempenho")

    st.caption(
        "Compara o tempo de resposta servido pelo cache local com o de uma "
        "chamada real à API externa, estimando o ganho de desempenho e o "
        "volume de acessos externos evitados — resultado central do TCC."
    )

    tem_cache = resumo["tempo_medio_cache_ms"] > 0
    tem_api = resumo["tempo_medio_api_ms"] > 0

    if not (tem_cache and tem_api):
        st.caption(
            "Ainda não há amostras suficientes de cache e API no mesmo "
            "período para montar o comparativo. Navegue pelo sistema até "
            "gerar tanto cache hits quanto chamadas reais à API."
        )
    else:
        cc1, cc2, cc3, cc4 = st.columns(4)

        cc1.metric("Tempo médio — Cache", f"{resumo['tempo_medio_cache_ms']:.1f} ms")

        cc2.metric("Tempo médio — API", f"{resumo['tempo_medio_api_ms']:.0f} ms")

        cc3.metric(
            "Redução de tempo com cache",
            f"{resumo['reducao_tempo_pct']:.1f}%",
        )

        cc4.metric(
            "Chamadas evitadas na API",
            resumo["chamadas_evitadas"],
            delta=f"~{resumo['tempo_total_economizado_ms'] / 1000:.2f} s economizados",
        )

        fig_comp = go.Figure(
            go.Bar(
                x=["Cache", "API"],
                y=[resumo["tempo_medio_cache_ms"], resumo["tempo_medio_api_ms"]],
                marker_color=["#2ecc71", "#3498db"],
                text=[
                    f"{resumo['tempo_medio_cache_ms']:.1f} ms",
                    f"{resumo['tempo_medio_api_ms']:.0f} ms",
                ],
                textposition="outside",
            )
        )

        fig_comp.update_layout(
            yaxis_title="Tempo médio de resposta (ms)",
            height=320,
            margin=dict(t=20, b=30),
            showlegend=False,
        )

        st.plotly_chart(fig_comp, use_container_width=True)

    st.divider()

    # =========================
    # Gráfico: tempo de resposta ao longo do tempo
    # =========================

    st.subheader("Tempo de resposta da API ao longo do tempo")

    chamadas_api = [
        r
        for r in resumo["linhas"]
        if not r["veio_do_cache"] and r["tempo_resposta_ms"] is not None
    ]

    if chamadas_api:
        chamadas_api_ordenadas = sorted(chamadas_api, key=lambda r: r["registrado_em"])

        datas = [r["registrado_em"] for r in chamadas_api_ordenadas]
        tempos = [r["tempo_resposta_ms"] for r in chamadas_api_ordenadas]

        fig = go.Figure(
            go.Scatter(
                x=datas,
                y=tempos,
                mode="lines+markers",
                name="Tempo de resposta (ms)",
            )
        )

        fig.update_layout(
            yaxis_title="ms",
            xaxis_title="Data/hora",
            height=350,
            margin=dict(t=10, b=40),
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(
            "Nenhuma chamada real à API neste período (tudo servido pelo cache)."
        )

    # =========================
    # Erros por ativo
    # =========================

    st.subheader("Erros por ativo")

    erros = erros_por_ticker(dias)

    if erros:
        tickers = [e["ticker"] for e in erros]
        totais = [e["total_erros"] for e in erros]

        fig_erros = go.Figure(
            go.Bar(
                x=totais,
                y=tickers,
                orientation="h",
                marker_color="#e74c3c",
            )
        )

        fig_erros.update_layout(
            xaxis_title="Nº de erros",
            yaxis_title="",
            height=100 + 35 * len(tickers),
            margin=dict(t=10, b=30),
        )

        st.plotly_chart(fig_erros, use_container_width=True)
    else:
        st.caption("Nenhum erro registrado neste período. ✅")

    # =========================
    # Log detalhado
    # =========================

    with st.expander("Ver log detalhado das requisições"):
        st.dataframe(
            resumo["linhas"],
            use_container_width=True,
            hide_index=True,
        )


# =========================
# Execução da página
# =========================

usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar as métricas.")
    st.stop()

render_metricas()
