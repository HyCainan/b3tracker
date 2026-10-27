import streamlit as st

st.set_page_config(
    page_title="Guia de indicadores | B3Tracker", page_icon="📚", layout="wide"
)

st.title("📚 Guia de indicadores técnicos")
st.caption(
    "Entenda o que cada indicador mede e como interpretar sinais em conjunto. "
    "Os exemplos são hipotéticos e não representam previsões nem recomendações de compra ou venda."
)

st.info(
    "Ideia principal: nenhum indicador deve ser interpretado isoladamente. "
    "Os indicadores descrevem aspectos diferentes do histórico de preços; eles não garantem o que acontecerá no futuro."
)

st.header("1. O que cada indicador mostra")
st.write("Use esta seção como referência ao consultar a página **Recomendações**.")

with st.expander(
    "📈 Tendência por regressão linear — direção histórica", expanded=True
):
    st.markdown(
        "- **O que mede:** resume a direção predominante dos preços ao longo do histórico analisado.\n"
        "- **Inclinação positiva:** trajetória histórica de alta.\n"
        "- **Inclinação negativa:** trajetória histórica de baixa.\n"
        "- **R²:** indica o quanto a reta ajustada representa a variação observada; não é a probabilidade de o preço subir.\n\n"
        "**Pergunta que ajuda a responder:** qual foi a direção predominante do preço?"
    )

with st.expander("〰️ Médias móveis SMA20 e SMA50 — direção e mudança"):
    st.markdown(
        "- **SMA20:** média dos fechamentos dos últimos 20 pregões.\n"
        "- **SMA50:** média dos fechamentos dos últimos 50 pregões.\n"
        "- **SMA20 acima da SMA50:** configuração relativa de alta.\n"
        "- **SMA20 abaixo da SMA50:** configuração relativa de baixa.\n"
        "- **Cruzamento:** indica que a relação entre as médias mudou recentemente.\n\n"
        "**Pergunta:** a média de curto prazo está acima ou abaixo da média de prazo mais longo?"
    )

with st.expander("⚡ RSI — intensidade dos movimentos recentes"):
    st.markdown(
        "O RSI varia de 0 a 100 e compara a intensidade dos ganhos e das perdas recentes.\n\n"
        "- **RSI ≥ 70:** condição chamada de sobrecompra pelo limite padrão do B3Tracker.\n"
        "- **RSI ≤ 30:** condição chamada de sobrevenda.\n"
        "- **Entre 30 e 70:** nenhuma dessas condições extremas foi acionada.\n\n"
        "Sobrecompra não garante queda, e sobrevenda não garante recuperação."
    )

with st.expander("🌊 Volatilidade anualizada — tamanho das oscilações"):
    st.markdown(
        "Estima a dispersão dos retornos diários e a expressa em uma escala anualizada. "
        "No B3Tracker, o padrão é sinalizar atenção a partir de **40%** e alerta a partir de **60%**.\n\n"
        "Volatilidade alta significa oscilações históricas maiores, não necessariamente desvalorização."
    )

with st.expander("📉 Drawdown — quedas em relação a um pico"):
    st.markdown(
        "- **Drawdown máximo:** maior queda entre um pico e um vale no período analisado.\n"
        "- **Drawdown atual:** distância percentual do último preço em relação ao maior preço do histórico analisado.\n\n"
        "A regra padrão sinaliza atenção quando o drawdown máximo chega a **−30% ou menos**. "
        "Isso descreve uma queda passada, não informa quando ou se haverá recuperação."
    )

with st.expander("💰 Prejuízo em relação ao preço médio — situação da sua posição"):
    st.markdown(
        "Compara o preço atual com o preço médio pago nas operações cadastradas. "
        "A regra padrão gera alerta quando a posição está **10% ou mais abaixo** do preço médio.\n\n"
        "Esse indicador depende das operações da carteira. Uma ação pode estar em tendência histórica de alta e, ainda assim, "
        "a sua posição estar no prejuízo se a compra foi feita a um preço maior."
    )

st.divider()
st.header("2. Como interpretar os indicadores em conjunto")
st.write(
    "Os cenários abaixo são exemplos didáticos. Os números são hipotéticos e servem para mostrar como os sinais se complementam, "
    "não para sugerir uma decisão de investimento."
)

cenarios = [
    {
        "titulo": "Tendência de alta + SMA20 acima da SMA50 + RSI 55",
        "sinais": "Direção histórica positiva; RSI fora das zonas de sobrecompra e sobrevenda.",
        "leitura": "Os sinais de direção são compatíveis entre si. Isso não garante continuidade da alta.",
    },
    {
        "titulo": "Tendência de alta + RSI 78 + volatilidade 65%",
        "sinais": "Trajetória histórica positiva, RSI elevado e oscilações intensas.",
        "leitura": "A alta ocorreu com movimento recente intenso e risco de oscilação elevado. O RSI não confirma uma queda futura.",
    },
    {
        "titulo": "Tendência de baixa + SMA20 abaixo da SMA50 + drawdown −35%",
        "sinais": "Direção histórica negativa, médias alinhadas para baixo e queda relevante desde um pico.",
        "leitura": "Os indicadores apontam aspectos diferentes, mas coerentes, de fraqueza histórica. Não indicam quando a queda terminará.",
    },
    {
        "titulo": "RSI 25 + drawdown −40%",
        "sinais": "Movimento recente de queda intenso e preço distante de um pico anterior.",
        "leitura": "Pode ocorrer recuperação ou continuidade da queda. Esses indicadores, sozinhos, não distinguem os dois resultados.",
    },
    {
        "titulo": "Tendência de alta + posição com prejuízo de 12%",
        "sinais": "O comportamento recente do ativo pode ser positivo, mas a cotação ainda está abaixo do preço médio de compra.",
        "leitura": "Tendência do ativo e resultado individual do investidor são coisas diferentes; o preço de entrada importa.",
    },
]

for cenario in cenarios:
    with st.expander(cenario["titulo"]):
        st.markdown(f"**O que os sinais mostram**  \n{cenario['sinais']}")
        st.markdown(f"**Como interpretar**  \n{cenario['leitura']}")

st.divider()
st.subheader("Resumo rápido")
st.table(
    {
        "Dimensão": [
            "Direção",
            "Momento",
            "Risco de oscilação",
            "Queda histórica",
            "Resultado pessoal",
        ],
        "Indicadores": [
            "Regressão linear e SMA20/SMA50",
            "RSI",
            "Volatilidade anualizada",
            "Drawdown",
            "Preço médio versus preço atual",
        ],
        "Pergunta principal": [
            "Qual foi a direção predominante?",
            "Os movimentos recentes foram intensos?",
            "Quanto o preço oscilou?",
            "Qual foi a queda em relação a um pico?",
            "Como a cotação se compara ao meu custo?",
        ],
    }
)

st.warning(
    "Conteúdo educacional. Os indicadores são baseados em dados históricos, podem divergir entre si e não consideram, por si só, "
    "fundamentos empresariais, notícias ou mudanças futuras. Não constituem aconselhamento financeiro."
)
