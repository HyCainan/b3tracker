import os
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from services.cache import (
    PERIODOS,
    TICKERS_DISPONIVEIS,
    buscar_ativo,
)

# =========================
# Configuração
# =========================

load_dotenv()

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")


def usuario_logado():
    return st.session_state.get("usuario")


def unix_to_date(ts):
    try:
        return datetime.fromtimestamp(
            int(ts),
            tz=timezone.utc,
        ).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def render_dashboard(token):
    """Renderiza cotações e gráfico."""

    st.title("📊 Dashboard")

    st.subheader("Cotações")

    col_left, col_right = st.columns([3, 1])

    with col_left:
        selecionados = st.multiselect(
            "Selecione os ativos",
            options=TICKERS_DISPONIVEIS,
            default=["PETR4", "VALE3"],
        )

    with col_right:
        periodo_label = st.selectbox(
            "Período do gráfico",
            options=list(PERIODOS.keys()),
            index=1,
        )

    if not selecionados:
        st.info("Selecione ao menos um ativo para ver as cotações.")

        return

    periodo = PERIODOS[periodo_label]

    resultados = []
    cache_hits = 0

    with st.spinner("Buscando cotações..."):
        for ticker in selecionados:
            try:
                stock, veio_do_cache = buscar_ativo(
                    ticker,
                    periodo,
                    token,
                )

                if stock:
                    resultados.append(stock)

                    if veio_do_cache:
                        cache_hits += 1

                else:
                    st.warning(f"Não foi possível buscar dados de {ticker}.")

            except Exception as e:
                st.error(f"Erro ao buscar {ticker}: {e}")

    if not resultados:
        st.error("Nenhum dado encontrado.")
        return

    if cache_hits:
        st.caption(
            f"⚡ {cache_hits}/{len(resultados)} cotações servidas pelo cache local."
        )

    # =========================
    # Cotação atual
    # =========================

    st.subheader("Cotação atual")

    cols = st.columns(len(resultados))

    for col, stock in zip(cols, resultados):
        change = stock.get(
            "regularMarketChangePercent",
            0,
        )

        price = stock.get(
            "regularMarketPrice",
            0,
        )

        high = stock.get(
            "regularMarketDayHigh",
            0,
        )

        low = stock.get(
            "regularMarketDayLow",
            0,
        )

        volume = stock.get(
            "regularMarketVolume",
            0,
        )

        arrow = "▲" if change >= 0 else "▼"

        with col:
            st.metric(
                label=stock["symbol"],
                value=f"R$ {price:.2f}",
                delta=f"{arrow} {change:.2f}%",
            )

            st.caption(f"Máx: R$ {high:.2f}")
            st.caption(f"Mín: R$ {low:.2f}")
            st.caption(f"Vol: {volume:,}")

    # =========================
    # Gráfico de rendimento
    # =========================

    st.subheader(f"Rendimento — {periodo_label}")

    fig = go.Figure()

    for stock in resultados:
        historico = stock.get(
            "historicalDataPrice",
            [],
        )

        if not historico:
            continue

        entradas = [(h["date"], h["close"]) for h in historico if h.get("close")]

        if not entradas:
            continue

        datas = [unix_to_date(d) for d, _ in entradas]

        precos = [p for _, p in entradas]

        base = precos[0]

        rendimento = [(p - base) / base * 100 for p in precos]

        fig.add_trace(
            go.Scatter(
                x=datas,
                y=rendimento,
                mode="lines",
                name=stock["symbol"],
                hovertemplate=("%{fullData.name}: %{y:.2f}%<br>%{x}<extra></extra>"),
            )
        )

    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="gray",
        opacity=0.5,
    )

    fig.update_layout(
        yaxis_title="Rendimento (%)",
        xaxis_title="Data",
        legend_title="Ativo",
        hovermode="x unified",
        height=420,
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
        fig,
        use_container_width=True,
    )


# =========================
# Execução da página
# =========================

if not usuario_logado():
    st.warning("Você precisa fazer login para acessar o dashboard.")

    st.stop()


if not BRAPI_TOKEN:
    st.error("Token da BRAPI não encontrado. Verifique o arquivo .env.")

    st.stop()


render_dashboard(BRAPI_TOKEN)
