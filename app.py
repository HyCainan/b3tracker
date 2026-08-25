import streamlit as st

from db.database import init_db

# =========================
# Configuração da aplicação
# =========================

"""streamlit run app.py"""

st.set_page_config(
    page_title="B3Tracker",
    page_icon="📈",
    layout="wide",
)

# Inicializa o banco de dados
init_db()


# =========================
# Página inicial
# =========================

st.title("📈 B3Tracker")

st.subheader("Monitoramento de ativos da B3")

st.write(
    "Utilize o menu lateral para acessar o login, dashboard, "
    "carteiras e simulador de investimentos."
)

usuario = st.session_state.get("usuario")

if usuario:
    st.success(f"Olá, {usuario['nome']}! Você está conectado.")
else:
    st.info("Acesse a página **Login** para entrar ou criar sua conta.")
