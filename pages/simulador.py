from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st


def unix_to_date(ts):
    try:
        return datetime.fromtimestamp(
            int(ts),
            tz=timezone.utc,
        ).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def render_simulador(
    resultados,
    periodo_label,
):

    st.title("🧮 Simulador de Investimento")

    st.caption(f"Simulação baseada no período: **{periodo_label}**")

    if not resultados:
        st.warning("Nenhum ativo disponível para simulação.")

        st.info(
            "Acesse o Dashboard primeiro, "
            "selecione os ativos e depois volte ao Simulador."
        )

        return

    st.divider()

    sim_col1, sim_col2 = st.columns([1, 2])

    # =========================
    # Valor investido
    # =========================

    with sim_col1:
        valor_investido = st.number_input(
            "Valor a investir (R$)",
            min_value=1.0,
            value=1000.0,
            step=100.0,
            format="%.2f",
        )

        st.caption("O valor será dividido igualmente entre os ativos selecionados.")

    n_ativos = len(resultados)

    valor_por_ativo = valor_investido / n_ativos if n_ativos > 0 else 0

    total_final = 0.0

    detalhes = []

    # =========================
    # Calcula investimento
    # =========================

    for stock in resultados:
        historico = stock.get(
            "historicalDataPrice",
            [],
        )

        entradas = [(h["date"], h["close"]) for h in historico if h.get("close")]

        if len(entradas) < 2:
            continue

        preco_inicial = entradas[0][1]
        preco_final = entradas[-1][1]

        retorno_pct = (preco_final - preco_inicial) / preco_inicial

        valor_final_ativo = valor_por_ativo * (1 + retorno_pct)

        ganho_ativo = valor_final_ativo - valor_por_ativo

        total_final += valor_final_ativo

        detalhes.append(
            {
                "symbol": stock["symbol"],
                "investido": valor_por_ativo,
                "final": valor_final_ativo,
                "ganho": ganho_ativo,
                "pct": retorno_pct * 100,
            }
        )

    ganho_total = total_final - valor_investido

    # =========================
    # Resultado
    # =========================

    with sim_col2:
        if not detalhes:
            st.warning("Não há dados históricos suficientes para realizar a simulação.")

            return

        res_cols = st.columns(len(detalhes) + 1)

        for i, d in enumerate(detalhes):
            with res_cols[i]:
                cor = "normal" if d["ganho"] >= 0 else "inverse"

                sinal = "+" if d["ganho"] >= 0 else ""

                st.metric(
                    label=d["symbol"],
                    value=f"R$ {d['final']:.2f}",
                    delta=(f"{sinal}R$ {d['ganho']:.2f} ({sinal}{d['pct']:.2f}%)"),
                    delta_color=cor,
                )

        # Total

        with res_cols[-1]:
            cor_total = "normal" if ganho_total >= 0 else "inverse"

            sinal_total = "+" if ganho_total >= 0 else ""

            percentual_total = ganho_total / valor_investido * 100

            st.metric(
                label="📊 Total da Carteira",
                value=f"R$ {total_final:.2f}",
                delta=(
                    f"{sinal_total}"
                    f"R$ {ganho_total:.2f} "
                    f"({sinal_total}"
                    f"{percentual_total:.2f}%)"
                ),
                delta_color=cor_total,
            )

    # =========================
    # Gráfico
    # =========================

    st.subheader(f"Evolução do capital investido — {periodo_label}")

    fig2 = go.Figure()

    for stock in resultados:
        historico = stock.get(
            "historicalDataPrice",
            [],
        )

        entradas = [(h["date"], h["close"]) for h in historico if h.get("close")]

        if len(entradas) < 2:
            continue

        datas = [unix_to_date(d) for d, _ in entradas]

        precos = [p for _, p in entradas]

        base = precos[0]

        capital = [valor_por_ativo * (p / base) for p in precos]

        fig2.add_trace(
            go.Scatter(
                x=datas,
                y=capital,
                mode="lines",
                name=stock["symbol"],
                hovertemplate=("%{fullData.name}: R$ %{y:.2f}<br>%{x}<extra></extra>"),
            )
        )

    fig2.add_hline(
        y=valor_por_ativo,
        line_dash="dash",
        line_color="gray",
        opacity=0.5,
        annotation_text=(f"Investido por ativo: R$ {valor_por_ativo:.2f}"),
        annotation_position="bottom right",
    )

    fig2.update_layout(
        yaxis_title="Valor (R$)",
        xaxis_title="Data",
        legend_title="Ativo",
        hovermode="x unified",
        height=400,
        margin=dict(
            t=20,
            b=40,
        ),
        xaxis=dict(
            type="category",
            tickangle=-45,
            nticks=12,
        ),
    )

    st.plotly_chart(
        fig2,
        use_container_width=True,
    )


# =========================
# Execução da página
# =========================

usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar o simulador.")

    st.stop()


resultados = st.session_state.get("resultados")

periodo_label = st.session_state.get("periodo_label")

if not resultados:
    st.info(
        "Para utilizar o simulador, "
        "acesse primeiro o Dashboard, "
        "selecione os ativos e depois volte aqui."
    )

else:
    render_simulador(
        resultados,
        periodo_label,
    )
