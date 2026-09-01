import os
from datetime import date

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from services.cache import PERIODOS, TICKERS_DISPONIVEIS, buscar_ativo
from services.carteira import (
    calcular_posicoes,
    criar_carteira,
    excluir_carteira,
    listar_carteiras,
    listar_operacoes,
    registrar_operacao,
    remover_operacao,
)

load_dotenv()
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")


# =========================
# Cálculo das métricas de performance
# =========================


def calcular_metricas_carteira(posicoes, token):
    """
    Para cada posição (quantidade + preço médio, vindos das operações
    reais), busca o preço atual de mercado e calcula o P/L com base no
    custo efetivo — não mais numa aproximação por variação de período.
    """
    detalhes = []
    total_investido = 0.0
    total_atual = 0.0

    with st.spinner("Calculando performance da carteira..."):
        for pos in posicoes:
            ticker = pos["ticker"]
            custo_total = pos["custo_total"]

            total_investido += custo_total

            try:
                stock, _ = buscar_ativo(ticker, "1mo", token)
            except Exception:
                stock = None

            if not stock:
                detalhes.append(
                    {
                        "ticker": ticker,
                        "quantidade": pos["quantidade"],
                        "preco_medio": pos["preco_medio"],
                        "custo_total": custo_total,
                        "valor_atual": custo_total,
                        "preco_atual": None,
                        "variacao_pct": 0.0,
                        "variacao_dia": 0.0,
                        "ganho": 0.0,
                        "erro": True,
                    }
                )
                total_atual += custo_total
                continue

            preco_atual = stock.get("regularMarketPrice", pos["preco_medio"])
            valor_atual = pos["quantidade"] * preco_atual
            ganho = valor_atual - custo_total
            variacao_pct = (ganho / custo_total * 100) if custo_total else 0.0

            total_atual += valor_atual

            detalhes.append(
                {
                    "ticker": ticker,
                    "quantidade": pos["quantidade"],
                    "preco_medio": pos["preco_medio"],
                    "custo_total": custo_total,
                    "valor_atual": valor_atual,
                    "preco_atual": preco_atual,
                    "variacao_pct": variacao_pct,
                    "variacao_dia": stock.get("regularMarketChangePercent", 0) or 0,
                    "ganho": ganho,
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


# =========================
# Painel de performance
# =========================


def render_performance_carteira(carteira_id, token):
    st.subheader("📈 Performance da carteira")

    posicoes = calcular_posicoes(carteira_id)

    if not posicoes:
        st.caption("Nenhuma posição em aberto. Registre uma compra para começar.")
        return

    metricas = calcular_metricas_carteira(posicoes, token)
    detalhes = metricas["detalhes"]

    if any(d["erro"] for d in detalhes):
        tickers_erro = ", ".join(d["ticker"] for d in detalhes if d["erro"])
        st.warning(
            f"Não foi possível obter a cotação de: {tickers_erro}. "
            "Essas posições foram consideradas ao preço médio (sem variação)."
        )

    col1, col2, col3 = st.columns(3)

    cor_total = "normal" if metricas["ganho_total"] >= 0 else "inverse"
    sinal_total = "+" if metricas["ganho_total"] >= 0 else ""

    col1.metric("Valor investido (custo)", f"R$ {metricas['total_investido']:.2f}")

    col2.metric(
        "Valor atual",
        f"R$ {metricas['total_atual']:.2f}",
        delta=(
            f"{sinal_total}R$ {metricas['ganho_total']:.2f} "
            f"({sinal_total}{metricas['variacao_total_pct']:.2f}%)"
        ),
        delta_color=cor_total,
    )

    validos = [d for d in detalhes if not d["erro"]]

    if validos:
        melhor = max(validos, key=lambda d: d["variacao_pct"])
        pior = min(validos, key=lambda d: d["variacao_pct"])

        with col3:
            st.caption("Destaques")
            st.write(
                f"🟢 Maior alta: **{melhor['ticker']}** ({melhor['variacao_pct']:+.2f}%)"
            )
            st.write(
                f"🔴 Maior queda: **{pior['ticker']}** ({pior['variacao_pct']:+.2f}%)"
            )

    st.caption("P/L calculado sobre o preço médio real das operações registradas.")

    # Gráfico comparativo
    if validos:
        ordenados = sorted(validos, key=lambda d: d["variacao_pct"], reverse=True)
        tickers_chart = [d["ticker"] for d in ordenados]
        variacoes_chart = [d["variacao_pct"] for d in ordenados]
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

    # Tabela detalhada
    st.caption("Posições em aberto")

    for d in detalhes:
        cols = st.columns([1.2, 1, 1.3, 1.3, 1.6, 1.6])

        cols[0].write(f"**{d['ticker']}**")
        cols[1].write(f"{d['quantidade']:g} un.")
        cols[2].write(f"PM: R$ {d['preco_medio']:.2f}")

        if d["erro"]:
            cols[3].write("—")
            cols[4].write("Sem dados")
            cols[5].write("—")
        else:
            cols[3].write(f"Atual: R$ {d['preco_atual']:.2f}")

            sinal = "+" if d["variacao_pct"] >= 0 else ""
            cor_texto = "green" if d["variacao_pct"] >= 0 else "red"
            cols[4].markdown(
                f":{cor_texto}[{sinal}R$ {d['ganho']:.2f} ({sinal}{d['variacao_pct']:.2f}%)]"
            )
            cols[5].caption(f"Valor atual: R$ {d['valor_atual']:.2f}")

    st.divider()


# =========================
# Página de carteiras
# =========================


def render_carteira(usuario_id, token):
    st.title("💼 Minhas Carteiras")

    carteiras = listar_carteiras(usuario_id)
    nomes = {c["nome"]: c["id"] for c in carteiras}
    opcoes = list(nomes.keys())

    col1, col2 = st.columns([2, 1])

    with col1:
        carteira_selecionada = st.selectbox(
            "Selecione uma carteira",
            options=(opcoes if opcoes else ["Nenhuma carteira criada"]),
            disabled=not opcoes,
        )

    with col2, st.popover("+ Nova carteira", use_container_width=True):
        nova = st.text_input("Nome da carteira")
        if st.button("Criar", key="btn_criar_carteira"):
            if nova.strip():
                criar_carteira(usuario_id, nova)
                st.success("Carteira criada com sucesso!")
                st.rerun()
            else:
                st.warning("Informe um nome.")

    if not opcoes:
        st.info("Crie sua primeira carteira para começar a registrar operações.")
        return

    carteira_id = nomes[carteira_selecionada]

    if st.button("🗑️ Excluir esta carteira"):
        excluir_carteira(carteira_id)
        st.success("Carteira excluída.")
        st.rerun()

    st.divider()

    # Performance
    if token:
        render_performance_carteira(carteira_id, token)
    else:
        st.warning("Token da BRAPI não encontrado. Verifique o arquivo .env.")

    # =========================
    # Registrar operação
    # =========================

    st.subheader("Registrar operação")

    with st.form("form_operacao"):
        c1, c2, c3, c4 = st.columns([1, 1.5, 1, 1.5])

        with c1:
            tipo = st.selectbox("Tipo", options=["compra", "venda"])

        with c2:
            ticker = st.selectbox("Ativo", options=TICKERS_DISPONIVEIS)

        with c3:
            quantidade = st.number_input(
                "Quantidade", min_value=1.0, value=10.0, step=1.0
            )

        with c4:
            preco = st.number_input(
                "Preço (R$)", min_value=0.01, value=10.0, step=0.5, format="%.2f"
            )

        data_operacao = st.date_input("Data da operação", value=date.today())

        enviar = st.form_submit_button("Registrar")

    if enviar:
        try:
            registrar_operacao(
                carteira_id,
                ticker,
                tipo,
                quantidade,
                preco,
                data_operacao.isoformat(),
            )
            st.success(f"{tipo.capitalize()} de {quantidade:g} {ticker} registrada.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    # =========================
    # Histórico de operações
    # =========================

    operacoes = listar_operacoes(carteira_id)

    if not operacoes:
        st.caption("Nenhuma operação registrada ainda.")
        return

    st.subheader("Histórico de operações")

    for op in operacoes:
        cols = st.columns([1, 2, 1.5, 1.5, 1.5, 1])

        emoji = "🟢" if op["tipo"] == "compra" else "🔴"
        cols[0].write(emoji)
        cols[1].write(op["ticker"])
        cols[2].write(f"{op['quantidade']:g} un.")
        cols[3].write(f"R$ {op['preco']:.2f}")
        cols[4].write(op["data_operacao"][:10])

        if cols[5].button("Remover", key=f"rm_op_{op['id']}"):
            remover_operacao(op["id"])
            st.rerun()


usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar suas carteiras.")
    st.stop()

render_carteira(usuario["id"], BRAPI_TOKEN)
