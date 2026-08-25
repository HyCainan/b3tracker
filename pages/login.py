import streamlit as st

from services.usuario import autenticar_usuario, criar_usuario


def render_login():
    st.title("📈 B3Tracker")
    st.caption("Monitoramento de ativos da B3 com carteira virtual")

    usuario_atual = st.session_state.get("usuario")

    if usuario_atual:
        st.success(f"Você já está conectado como **{usuario_atual['nome']}**.")

        if st.button("Sair"):
            del st.session_state["usuario"]
            st.rerun()

        return

    _, col_centro, _ = st.columns([1, 2, 1])

    with col_centro:
        aba_login, aba_cadastro = st.tabs(["Entrar", "Criar conta"])

        # =========================
        # Login
        # =========================

        with aba_login:
            with st.form("form_login"):
                email = st.text_input("E-mail")
                senha = st.text_input("Senha", type="password")

                enviar = st.form_submit_button(
                    "Entrar",
                    use_container_width=True,
                )

            if enviar:
                if not email or not senha:
                    st.warning("Preencha e-mail e senha.")
                else:
                    resultado = autenticar_usuario(email, senha)

                    if resultado["ok"]:
                        st.session_state["usuario"] = resultado["usuario"]

                        st.success("Login realizado com sucesso!")
                        st.rerun()
                    else:
                        st.error(resultado["erro"])

        # =========================
        # Cadastro
        # =========================

        with aba_cadastro:
            with st.form("form_cadastro"):
                nome = st.text_input("Nome")

                email_cad = st.text_input(
                    "E-mail",
                    key="cad_email",
                )

                senha_cad = st.text_input(
                    "Senha",
                    type="password",
                    key="cad_senha",
                )

                senha_confirma = st.text_input(
                    "Confirmar senha",
                    type="password",
                )

                enviar_cad = st.form_submit_button(
                    "Criar conta",
                    use_container_width=True,
                )

            if enviar_cad:
                if not nome or not email_cad or not senha_cad:
                    st.warning("Preencha todos os campos.")

                elif senha_cad != senha_confirma:
                    st.warning("As senhas não coincidem.")

                elif len(senha_cad) < 6:
                    st.warning("A senha deve ter pelo menos 6 caracteres.")

                else:
                    resultado = criar_usuario(
                        nome,
                        email_cad,
                        senha_cad,
                    )

                    if resultado["ok"]:
                        st.success(
                            "Conta criada com sucesso! Faça login na aba ao lado."
                        )
                    else:
                        st.error(resultado["erro"])


# =========================
# Executa a página
# =========================

render_login()
