import os
from datetime import date

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from services.cache import TICKERS_DISPONIVEIS, buscar_ativo
from services.carteira import (
    calcular_posicoes,
    criar_carteira,
    excluir_carteira,
    listar_carteiras,
    listar_operacoes,
    registrar_operacao,
    remover_operacao,
)
from services.renda_fixa import (
    calcular_posicoes as calcular_posicoes_rf,
    listar_aportes,
    registrar_aporte,
    remover_aporte,
)

load_dotenv()
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")


# =========================
# Cálculo das métricas de performance (ações)
# =========================


def calcular_metricas_acoes(posicoes, token):
    """
    Para cada posição (quantidade + preço médio, vindos das operações
    reais), busca o preço atual de mercado e calcula o P/L com base no
    custo efetivo.
    """
    detalhes = []
    total_investido = 0.0
    total_atual = 0.0

    with st.spinner("Calculando performance das ações..."):
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
# Painel de performance (ações + renda fixa)
# =========================


def render_performance_carteira(carteira_id, token):
    st.subheader("📈 Performance da carteira")

    posicoes_acoes = calcular_posicoes(carteira_id)
    posicoes_rf = calcular_posicoes_rf(carteira_id)

    if not posicoes_acoes and not posicoes_rf:
        st.caption(
            "Nenhuma posição em aberto. Registre uma compra ou um aporte para começar."
        )
        return

    linhas = []
    total_investido = 0.0
    total_atual = 0.0

    if posicoes_acoes:
        metricas_acoes = calcular_metricas_acoes(posicoes_acoes, token)

        for d in metricas_acoes["detalhes"]:
            linhas.append(
                {
                    "rotulo": d["ticker"],
                    "categoria": "Ação",
                    "valor_investido": d["custo_total"],
                    "valor_atual": d["valor_atual"],
                    "variacao_pct": d["variacao_pct"],
                    "erro": d["erro"],
                }
            )

        total_investido += metricas_acoes["total_investido"]
        total_atual += metricas_acoes["total_atual"]

    for d in posicoes_rf:
        linhas.append(
            {
                "rotulo": d["rotulo"],
                "categoria": "Renda Fixa",
                "valor_investido": d["valor_aportado"],
                "valor_atual": d["valor_atual"],
                "variacao_pct": d["variacao_pct"],
                "erro": d["erro"],
            }
        )
        total_investido += d["valor_aportado"]
        total_atual += d["valor_atual"]

    ganho_total = total_atual - total_investido
    variacao_total_pct = (
        (ganho_total / total_investido * 100) if total_investido else 0.0
    )

    if any(l["erro"] for l in linhas):
        rotulos_erro = ", ".join(l["rotulo"] for l in linhas if l["erro"])
        st.warning(
            f"Não foi possível obter a cotação/rendimento de: {rotulos_erro}. "
            "Essas posições foram consideradas sem variação."
        )

    col1, col2, col3 = st.columns(3)

    cor_total = "normal" if ganho_total >= 0 else "inverse"
    sinal_total = "+" if ganho_total >= 0 else ""

    col1.metric("Valor investido", f"R$ {total_investido:.2f}")

    col2.metric(
        "Valor atual",
        f"R$ {total_atual:.2f}",
        delta=(
            f"{sinal_total}R$ {ganho_total:.2f} ({sinal_total}{variacao_total_pct:.2f}%)"
        ),
        delta_color=cor_total,
    )

    validos = [l for l in linhas if not l["erro"]]

    if validos:
        melhor = max(validos, key=lambda l: l["variacao_pct"])
        pior = min(validos, key=lambda l: l["variacao_pct"])

        with col3:
            st.caption("Destaques")
            st.write(
                f"🟢 Maior alta: **{melhor['rotulo']}** ({melhor['variacao_pct']:+.2f}%)"
            )
            st.write(
                f"🔴 Maior queda: **{pior['rotulo']}** ({pior['variacao_pct']:+.2f}%)"
            )

    st.caption(
        "P/L de ações calculado sobre o preço médio real das operações; "
        "renda fixa calculada sobre o rendimento acumulado do indexador desde o aporte."
    )

    # Gráfico comparativo
    if validos:
        ordenados = sorted(validos, key=lambda l: l["variacao_pct"], reverse=True)
        rotulos_chart = [l["rotulo"] for l in ordenados]
        variacoes_chart = [l["variacao_pct"] for l in ordenados]
        cores_chart = ["#2ecc71" if v >= 0 else "#e74c3c" for v in variacoes_chart]

        fig = go.Figure(
            go.Bar(
                x=variacoes_chart,
                y=rotulos_chart,
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
            height=120 + 40 * len(rotulos_chart),
            margin=dict(t=10, b=30, l=10, r=10),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Tabela detalhada
    st.caption("Posições em aberto")

    for l in linhas:
        cols = st.columns([1.6, 1.6, 1.4, 1.4])

        cols[0].write(f"**{l['rotulo']}**")
        cols[0].caption(l["categoria"])

        cols[1].write(f"Investido: R$ {l['valor_investido']:.2f}")

        if l["erro"]:
            cols[2].write("Sem dados")
            cols[3].write("—")
        else:
            sinal = "+" if l["variacao_pct"] >= 0 else ""
            cor_texto = "green" if l["variacao_pct"] >= 0 else "red"
            cols[2].markdown(f":{cor_texto}[{sinal}{l['variacao_pct']:.2f}%]")
            cols[3].caption(f"Valor atual: R$ {l['valor_atual']:.2f}")

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
    # Registrar operação (ações)
    # =========================

    st.subheader("Registrar operação (Ação B3)")

    c1, c2 = st.columns([1, 1.5])

    with c1:
        tipo = st.selectbox("Tipo", options=["compra", "venda"], key="op_tipo")

    with c2:
        ticker = st.selectbox("Ativo", options=TICKERS_DISPONIVEIS, key="op_ticker")

    forma = st.selectbox(
        "Forma de compra" if tipo == "compra" else "Forma de venda",
        options=["Por valor", "Por quantidade"],
        key="op_forma",
    )

    # Busca a cotação atual do ativo escolhido para permitir o cálculo
    # em tempo real (tanto pra "por valor" quanto pra exibir o valor da
    # operação em "por quantidade").
    preco_atual = None
    if token:
        try:
            stock, _ = buscar_ativo(ticker, "1mo", token)
            if stock:
                preco_atual = stock.get("regularMarketPrice")
        except Exception:
            preco_atual = None

    if preco_atual is None:
        st.warning(
            "Não foi possível obter a cotação atual deste ativo agora. "
            "Tente novamente em instantes."
        )
    else:
        quantidade = None
        valor_operacao = None

        if forma == "Por valor":
            valor_investir = st.number_input(
                "Valor a investir (R$)" if tipo == "compra" else "Valor a vender (R$)",
                min_value=0.01,
                value=100.0,
                step=50.0,
                format="%.2f",
                key="op_valor_investir",
            )

            quantidade = float(int(valor_investir // preco_atual))
            valor_operacao = quantidade * preco_atual

            m1, m2, m3 = st.columns(3)
            m1.metric("Cotação atual", f"R$ {preco_atual:.2f}")
            m2.metric("Quantidade estimada", f"{quantidade:g} ações")
            m3.metric("Valor da operação", f"R$ {valor_operacao:.2f}")

            if quantidade <= 0:
                st.warning(
                    "O valor informado não é suficiente para "
                    f"{'comprar' if tipo == 'compra' else 'vender'} nem 1 ação."
                )

        else:  # Por quantidade
            quantidade = st.number_input(
                "Quantidade",
                min_value=1.0,
                value=10.0,
                step=1.0,
                format="%.0f",
                key="op_quantidade",
            )

            valor_operacao = quantidade * preco_atual

            m1, m2 = st.columns(2)
            m1.metric("Cotação atual", f"R$ {preco_atual:.2f}")
            m2.metric("Valor da operação", f"R$ {valor_operacao:.2f}")

        data_operacao = st.date_input(
            "Data da operação", value=date.today(), key="op_data"
        )

        if st.button("Registrar", disabled=(not quantidade or quantidade <= 0)):
            try:
                registrar_operacao(
                    carteira_id,
                    ticker,
                    tipo,
                    quantidade,
                    preco_atual,
                    data_operacao.isoformat(),
                )
                st.success(
                    f"{tipo.capitalize()} de {quantidade:g} {ticker} registrada "
                    f"(R$ {valor_operacao:.2f})."
                )
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # =========================
    # Histórico de operações (ações)
    # =========================

    operacoes = listar_operacoes(carteira_id)

    if operacoes:
        st.subheader("Histórico de operações (Ações)")

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

    st.divider()

    # =========================
    # Registrar aporte (Renda Fixa: CDI/Selic)
    # =========================

    st.subheader("Registrar aporte em Renda Fixa (CDI/Selic)")

    rf1, rf2, rf3 = st.columns([1, 1, 1.5])

    with rf1:
        indexador_sel = st.selectbox(
            "Indexador", options=["CDI", "SELIC"], key="rf_indexador"
        )

    with rf2:
        percentual_sel = st.number_input(
            "% do indexador",
            min_value=1.0,
            value=100.0,
            step=5.0,
            key="rf_percentual",
        )

    with rf3:
        valor_sel = st.number_input(
            "Valor aportado (R$)",
            min_value=1.0,
            value=100.0,
            step=50.0,
            key="rf_valor",
        )

    data_aporte = st.date_input("Data do aporte", value=date.today(), key="rf_data")

    if st.button("Registrar aporte"):
        try:
            registrar_aporte(
                carteira_id,
                indexador_sel,
                percentual_sel,
                valor_sel,
                data_aporte.isoformat(),
            )
            st.success(
                f"Aporte de R$ {valor_sel:.2f} em {indexador_sel} "
                f"{percentual_sel:.0f}% registrado."
            )
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    # =========================
    # Histórico de aportes (Renda Fixa)
    # =========================

    aportes = listar_aportes(carteira_id)

    if aportes:
        st.subheader("Histórico de aportes (Renda Fixa)")

        for ap in aportes:
            cols = st.columns([2, 1.5, 1.5, 1])

            cols[0].write(f"{ap['indexador']} {ap['percentual_indexador']:.0f}%")
            cols[1].write(f"R$ {ap['valor']:.2f}")
            cols[2].write(ap["data_operacao"][:10])

            if cols[3].button("Remover", key=f"rm_rf_{ap['id']}"):
                remover_aporte(ap["id"])
                st.rerun()


usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar suas carteiras.")
    st.stop()

render_carteira(usuario["id"], BRAPI_TOKEN)
