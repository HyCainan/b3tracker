import os

import streamlit as st
from dotenv import load_dotenv

from services.carteira import listar_carteiras
from services.Recomendacao import gerar_recomendacoes

load_dotenv()
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN")


def _dinheiro(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_recomendacoes():
    st.title("💡 Recomendações e análise da carteira")
    st.caption(
        "Análise informativa baseada na composição da carteira, no histórico de preços "
        "e em regras configuráveis. Indicadores técnicos descrevem o passado e não "
        "preveem preços futuros; isto não é recomendação profissional de investimento."
    )

    usuario = st.session_state.get("usuario")
    if not usuario:
        st.warning("Você precisa fazer login para analisar suas carteiras.")
        st.stop()

    carteiras = listar_carteiras(usuario["id"])
    if not carteiras:
        st.info("Você ainda não possui carteiras. Crie uma na página Carteiras.")
        return

    carteira_por_nome = {f"{c['nome']} (ID {c['id']})": c for c in carteiras}
    selecionada = st.selectbox("Selecione a carteira", list(carteira_por_nome))
    carteira = carteira_por_nome[selecionada]

    with st.expander("Configurar limites da análise"):
        c1, c2, c3 = st.columns(3)
        concentracao = c1.number_input(
            "Concentração máxima por ativo (%)", 1.0, 100.0, 40.0, 1.0
        )
        prejuizo = c2.number_input("Alerta de prejuízo (%)", 1.0, 100.0, 10.0, 1.0)
        vol = c3.number_input("Volatilidade para atenção (%)", 1.0, 200.0, 40.0, 5.0)
        c4, c5, c6 = st.columns(3)
        rsi_compra = c4.number_input("RSI sobrecompra", 50.0, 100.0, 70.0, 1.0)
        rsi_venda = c5.number_input("RSI sobrevenda", 0.0, 50.0, 30.0, 1.0)
        hhi = c6.number_input("Limite HHI", 0.01, 1.0, 0.25, 0.01)

    limites = {
        "concentracao_max_pct": concentracao,
        "prejuizo_max_pct": prejuizo,
        "vol_atencao_pct": vol,
        "rsi_sobrecompra": rsi_compra,
        "rsi_sobrevenda": rsi_venda,
        "hhi_max": hhi,
    }

    if not BRAPI_TOKEN:
        st.warning(
            "Token da brapi.dev não encontrado. Confira BRAPI_TOKEN no arquivo .env."
        )
        st.stop()

    if st.button("🔎 Analisar carteira", type="primary"):
        with st.spinner("Buscando cotações e calculando indicadores..."):
            try:
                resultado = gerar_recomendacoes(carteira["id"], BRAPI_TOKEN, limites)
                st.session_state["resultado_recomendacoes"] = resultado
                st.session_state["resultado_recomendacoes_carteira"] = carteira["id"]
            except Exception as exc:
                st.error(f"Não foi possível concluir a análise: {exc}")
                st.stop()

    resultado = st.session_state.get("resultado_recomendacoes")
    if (
        not resultado
        or st.session_state.get("resultado_recomendacoes_carteira") != carteira["id"]
    ):
        st.info("Clique em **Analisar carteira** para gerar os indicadores e alertas.")
        return

    resumo = resultado["resumo"]
    st.divider()
    st.subheader("Resumo da carteira")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Patrimônio estimado", _dinheiro(resumo["total_carteira"]))
    k2.metric("Renda variável", f"{resumo['pct_renda_variavel']:.1f}%")
    k3.metric("Renda fixa", f"{resumo['pct_renda_fixa']:.1f}%")
    k4.metric(
        "HHI das ações",
        f"{resumo['hhi_acoes']:.3f}" if resumo["hhi_acoes"] is not None else "N/D",
    )

    comparacao = resumo.get("comparacao_cdi")
    if comparacao:
        st.subheader("Desempenho versus CDI")
        a, b, c = st.columns(3)
        a.metric(
            "Retorno estimado da carteira",
            f"{comparacao['retorno_carteira_pct']:+.2f}%",
        )
        b.metric("Referência 100% CDI", f"{comparacao['retorno_cdi_pct']:+.2f}%")
        diferenca = comparacao["retorno_carteira_pct"] - comparacao["retorno_cdi_pct"]
        c.metric("Diferença", f"{diferenca:+.2f} p.p.")

    st.divider()
    st.subheader(f"Alertas e recomendações ({len(resultado['recomendacoes'])})")
    if not resultado["recomendacoes"]:
        st.success("Nenhuma regra de alerta foi acionada com os limites atuais.")
    else:
        for i, rec in enumerate(resultado["recomendacoes"]):
            icon = {"alerta": "🚨", "atencao": "⚠️", "info": "ℹ️"}.get(
                rec.severidade, "•"
            )
            titulo = f"{icon} {rec.titulo}"
            if rec.ativo:
                titulo += f" — {rec.ativo}"
            with st.expander(titulo, expanded=(i == 0 and rec.severidade == "alerta")):
                st.write(rec.mensagem)
                st.caption(
                    f"Regra: {rec.regra} · Escopo: {rec.escopo} · Severidade: {rec.severidade}"
                )
                if rec.evidencia:
                    st.json(rec.evidencia)

    indicadores = resultado.get("indicadores", {})
    if indicadores:
        st.divider()
        st.subheader("Indicadores por ativo")
        linhas = []
        for ticker, ind in indicadores.items():
            if not ind:
                linhas.append(
                    {
                        "Ativo": ticker,
                        "Pregões": "N/D",
                        "Tendência anual": "N/D",
                        "R²": "N/D",
                        "RSI(14)": "N/D",
                        "Volatilidade anual": "N/D",
                        "Drawdown máximo": "N/D",
                    }
                )
                continue
            tendencia = ind.get("tendencia") or {}
            dd = ind.get("drawdown") or {}
            linhas.append(
                {
                    "Ativo": ticker,
                    "Pregões": ind.get("n_pregoes", "N/D"),
                    "Tendência anual": f"{tendencia['tendencia_anual_pct']:+.1f}%"
                    if tendencia
                    else "N/D",
                    "R²": f"{tendencia['r2']:.2f}" if tendencia else "N/D",
                    "RSI(14)": f"{ind['rsi']:.1f}"
                    if ind.get("rsi") is not None
                    else "N/D",
                    "Volatilidade anual": f"{ind['volatilidade_pct']:.1f}%"
                    if ind.get("volatilidade_pct") is not None
                    else "N/D",
                    "Drawdown máximo": f"{dd['max_pct']:.1f}%" if dd else "N/D",
                }
            )
        st.dataframe(linhas, use_container_width=True, hide_index=True)

    if resultado.get("avisos"):
        st.divider()
        st.subheader("Avisos sobre os dados")
        for aviso in resultado["avisos"]:
            st.warning(aviso)


render_recomendacoes()
