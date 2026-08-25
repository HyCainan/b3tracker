import os

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from services.cache import (
    PERIODOS,
    TICKERS_DISPONIVEIS,
    buscar_ativo,
)
from services.carteira import (
    adicionar_ativo,
    criar_carteira,
    excluir_carteira,
    listar_ativos,
    listar_carteiras,
    remover_ativo,
)

# =========================
# Configuração
# =========================

load_dotenv()

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")


# =========================
# Cálculo das métricas
# =========================


def calcular_metricas_carteira(ativos, periodo, token):
    """
    Busca a cotação de cada ativo da carteira no período selecionado e
    calcula a performance individual e consolidada.

    A variação de cada ativo é obtida comparando o primeiro e o último
    preço de fechamento do histórico do período. Essa variação é aplicada
    sobre o valor alocado para estimar o valor atual da posição.
    """
    detalhes = []
    total_investido = 0.0
    total_atual = 0.0

    with st.spinner("Calculando performance da carteira..."):
        for ativo in ativos:
            ticker = ativo["ticker"]
            valor_alocado = ativo["valor_alocado"]

            total_investido += valor_alocado

            try:
                stock, _ = buscar_ativo(ticker, periodo, token)
            except Exception:
                stock = None

            if not stock:
                detalhes.append(
                    {
                        "id": ativo["id"],
                        "ticker": ticker,
                        "valor_alocado": valor_alocado,
                        "valor_atual": valor_alocado,
                        "variacao_pct": 0.0,
                        "variacao_dia": 0.0,
                        "ganho": 0.0,
                        "preco_atual": None,
                        "erro": True,
                    }
                )
                total_atual += valor_alocado
                continue

            historico = stock.get("historicalDataPrice", [])
            entradas = [(h["date"], h["close"]) for h in historico if h.get("close")]

            if len(entradas) >= 2:
                preco_inicial = entradas[0][1]
                preco_final = entradas[-1][1]
                variacao_pct = (preco_final - preco_inicial) / preco_inicial * 100
            else:
                variacao_pct = 0.0

            valor_atual = valor_alocado * (1 + variacao_pct / 100)
            ganho = valor_atual - valor_alocado

            total_atual += valor_atual

            detalhes.append(
                {
                    "id": ativo["id"],
                    "ticker": ticker,
                    "valor_alocado": valor_alocado,
                    "valor_atual": valor_atual,
                    "variacao_pct": variacao_pct,
                    "variacao_dia": stock.get("regularMarketChangePercent", 0) or 0,
                    "ganho": ganho,
                    "preco_atual": stock.get("regularMarketPrice"),
                    "erro": False,
                }
            )

    ganho_total = total_atual - total_investido
    variacao_total_pct = (
        (ganho_total / total_investido * 100) if total_investido else 0.0
    )

    return {
        "detalhes": detalhes,
        "total_investido": total_investido,
        "total_atual": total_atual,
        "ganho_total": ganho_total,
        "variacao_total_pct": variacao_total_pct,
    }


def consolidar_por_ticker(detalhes):
    """
    Agrupa múltiplas entradas do mesmo ticker (ex: duas compras de PETR4)
    em uma única posição consolidada, somando valor alocado e valor atual
    e recalculando a variação percentual sobre o total.
    """
    agregados = {}
    ordem = []

    for d in detalhes:
        ticker = d["ticker"]

        if ticker not in agregados:
            agregados[ticker] = {
                "ticker": ticker,
                "valor_alocado": 0.0,
                "valor_atual": 0.0,
                "ganho": 0.0,
                "preco_atual": d["preco_atual"],
                "variacao_dia": d["variacao_dia"],
                "erro": False,
            }
            ordem.append(ticker)

        agg = agregados[ticker]

        agg["valor_alocado"] += d["valor_alocado"]
        agg["valor_atual"] += d["valor_atual"]
        agg["ganho"] += d["ganho"]
        agg["erro"] = agg["erro"] or d["erro"]

        if not d["erro"]:
            agg["preco_atual"] = d["preco_atual"]
            agg["variacao_dia"] = d["variacao_dia"]

    consolidado = []

    for ticker in ordem:
        agg = agregados[ticker]

        agg["variacao_pct"] = (
            (agg["ganho"] / agg["valor_alocado"] * 100) if agg["valor_alocado"] else 0.0
        )

        consolidado.append(agg)

    return consolidado


# =========================
# Renderização do painel de performance
# =========================


def render_performance_carteira(ativos, token):

    st.subheader("📈 Performance da carteira")

    periodo_label = st.selectbox(
        "Período de análise",
        options=list(PERIODOS.keys()),
        index=1,
        key="periodo_performance_carteira",
    )

    periodo = PERIODOS[periodo_label]

    metricas = calcular_metricas_carteira(ativos, periodo, token)

    consolidado = consolidar_por_ticker(metricas["detalhes"])

    if any(d["erro"] for d in consolidado):
        tickers_erro = ", ".join(d["ticker"] for d in consolidado if d["erro"])
        st.warning(
            f"Não foi possível obter a cotação de: {tickers_erro}. "
            "Esses ativos foram considerados sem variação no período."
        )

    # =========================
    # Resumo consolidado
    # =========================

    col1, col2, col3 = st.columns(3)

    cor_total = "normal" if metricas["ganho_total"] >= 0 else "inverse"
    sinal_total = "+" if metricas["ganho_total"] >= 0 else ""

    col1.metric(
        "Valor investido",
        f"R$ {metricas['total_investido']:.2f}",
    )

    col2.metric(
        "Valor atual estimado",
        f"R$ {metricas['total_atual']:.2f}",
        delta=(
            f"{sinal_total}R$ {metricas['ganho_total']:.2f} "
            f"({sinal_total}{metricas['variacao_total_pct']:.2f}%)"
        ),
        delta_color=cor_total,
    )

    ativos_validos = [d for d in consolidado if not d["erro"]]

    if ativos_validos:
        melhor = max(ativos_validos, key=lambda d: d["variacao_pct"])
        pior = min(ativos_validos, key=lambda d: d["variacao_pct"])

        with col3:
            st.caption("Destaques do período")
            st.write(
                f"🟢 Maior alta: **{melhor['ticker']}** ({melhor['variacao_pct']:+.2f}%)"
            )
            st.write(
                f"🔴 Maior queda: **{pior['ticker']}** ({pior['variacao_pct']:+.2f}%)"
            )

    st.caption(
        f"Estimativa baseada na variação de preço no período **{periodo_label}**, "
        "aplicada sobre o valor alocado a cada ativo."
    )

    # =========================
    # Gráfico comparativo
    # =========================

    if ativos_validos:
        detalhes_ordenados = sorted(
            ativos_validos, key=lambda d: d["variacao_pct"], reverse=True
        )

        tickers_chart = [d["ticker"] for d in detalhes_ordenados]
        variacoes_chart = [d["variacao_pct"] for d in detalhes_ordenados]
        cores_chart = ["#2ecc71" if v >= 0 else "#e74c3c" for v in variacoes_chart]

        fig = go.Figure(
            go.Bar(
                x=variacoes_chart,
                y=tickers_chart,
                orientation="h",
                marker_color=cores_chart,
                text=[f"{v:+.2f}%" for v in variacoes_chart],
                textposition="outside",
            )
        )

        fig.add_vline(x=0, line_color="gray", opacity=0.5)

        fig.update_layout(
            xaxis_title="Variação (%)",
            yaxis_title="",
            height=120 + 40 * len(tickers_chart),
            margin=dict(t=10, b=30, l=10, r=10),
            showlegend=False,
        )

        st.plotly_chart(fig, use_container_width=True)

    # =========================
    # Tabela detalhada por ativo
    # =========================

    st.caption("Detalhamento por ativo")

    for d in consolidado:
        cols = st.columns([1.5, 1.5, 1.5, 1.5, 1.5])

        cols[0].write(f"**{d['ticker']}**")
        cols[1].write(f"R$ {d['valor_alocado']:.2f}")

        if d["erro"]:
            cols[2].write("—")
            cols[3].write("Sem dados")
            cols[4].write("—")
        else:
            cols[2].write(f"R$ {d['valor_atual']:.2f}")

            sinal = "+" if d["variacao_pct"] >= 0 else ""
            cor_texto = "green" if d["variacao_pct"] >= 0 else "red"
            cols[3].markdown(
                f":{cor_texto}[{sinal}{d['variacao_pct']:.2f}% no período]"
            )

            if d["preco_atual"] is not None:
                cols[4].caption(f"Preço atual: R$ {d['preco_atual']:.2f}")

    st.divider()


# =========================
# Página de carteiras
# =========================


def render_carteira(usuario_id, token):

    st.title("💼 Minhas Carteiras")

    carteiras = listar_carteiras(usuario_id)

    nomes = {c["nome"]: c["id"] for c in carteiras}

    opcoes = list(nomes.keys())

    # =========================
    # Criar carteira
    # =========================

    col1, col2 = st.columns([2, 1])

    with col1:
        carteira_selecionada = st.selectbox(
            "Selecione uma carteira",
            options=(opcoes if opcoes else ["Nenhuma carteira criada"]),
            disabled=not opcoes,
        )

    with (
        col2,
        st.popover(
            "+ Nova carteira",
            use_container_width=True,
        ),
    ):
        nova = st.text_input("Nome da carteira")

        if st.button(
            "Criar",
            key="btn_criar_carteira",
        ):
            if nova.strip():
                criar_carteira(
                    usuario_id,
                    nova,
                )

                st.success("Carteira criada com sucesso!")

                st.rerun()

            else:
                st.warning("Informe um nome.")

    if not opcoes:
        st.info("Crie sua primeira carteira para começar a salvar ativos.")

        return

    carteira_id = nomes[carteira_selecionada]

    # =========================
    # Excluir carteira
    # =========================

    if st.button("🗑️ Excluir esta carteira"):
        excluir_carteira(carteira_id)

        st.success("Carteira excluída.")

        st.rerun()

    st.divider()

    # =========================
    # Performance da carteira
    # =========================

    ativos = listar_ativos(carteira_id)

    if ativos and token:
        render_performance_carteira(ativos, token)
    elif ativos and not token:
        st.warning("Token da BRAPI não encontrado. Verifique o arquivo .env.")

    # =========================
    # Adicionar ativo
    # =========================

    st.subheader("Ativos da carteira")

    with st.form("form_add_ativo"):
        c1, c2, c3 = st.columns([2, 2, 1])

        with c1:
            ticker = st.selectbox(
                "Ativo",
                options=TICKERS_DISPONIVEIS,
            )

        with c2:
            valor = st.number_input(
                "Valor alocado (R$)",
                min_value=1.0,
                value=100.0,
                step=50.0,
            )

        with c3:
            st.write("")
            st.write("")

            adicionar = st.form_submit_button("Adicionar")

    if adicionar:
        adicionar_ativo(
            carteira_id,
            ticker,
            valor,
        )

        st.success(f"{ticker} adicionado à carteira.")

        st.rerun()

    # =========================
    # Listar ativos (cadastro)
    # =========================

    if not ativos:
        st.caption("Nenhum ativo adicionado ainda.")

        return

    for ativo in ativos:
        cols = st.columns([2, 2, 2, 1])

        cols[0].write(ativo["ticker"])

        cols[1].write(f"R$ {ativo['valor_alocado']:.2f}")

        cols[2].write(ativo["adicionado_em"][:10])

        if cols[3].button(
            "Remover",
            key=f"rm_{ativo['id']}",
        ):
            remover_ativo(ativo["id"])

            st.rerun()


# =========================
# Execução da página
# =========================

usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar suas carteiras.")

    st.stop()


render_carteira(usuario["id"], BRAPI_TOKEN)
