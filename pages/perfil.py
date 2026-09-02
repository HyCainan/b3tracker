from datetime import datetime

import streamlit as st

from services.carteira import calcular_posicoes, listar_carteiras
from services.usuario import (
    atualizar_email,
    atualizar_nome,
    atualizar_senha,
    buscar_usuario_por_id,
    excluir_usuario,
)


def formatar_data(iso_str):
    try:
        return datetime.fromisoformat(iso_str).strftime("%d/%m/%Y")
    except Exception:
        return iso_str


def calcular_estatisticas(usuario_id):
    """Resumo de uso: nº de carteiras, ativos em posição e custo total investido."""
    carteiras = listar_carteiras(usuario_id)

    total_ativos = 0
    custo_total = 0.0

    for c in carteiras:
        posicoes = calcular_posicoes(c["id"])
        total_ativos += len(posicoes)
        custo_total += sum(p["custo_total"] for p in posicoes)

    return {
        "total_carteiras": len(carteiras),
        "total_ativos": total_ativos,
        "valor_total_alocado": custo_total,
    }


def render_perfil(usuario_id):
    st.title("👤 Meu perfil")

    dados = buscar_usuario_por_id(usuario_id)

    if not dados:
        st.error("Não foi possível carregar os dados do usuário.")
        st.stop()

    # =========================
    # Resumo
    # =========================

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown(f"### {dados['nome']}")
        st.caption(dados["email"])
        if dados.get("criado_em"):
            st.caption(f"Conta criada em {formatar_data(dados['criado_em'])}")

    stats = calcular_estatisticas(usuario_id)

    with col2:
        s1, s2, s3 = st.columns(3)
        s1.metric("Carteiras", stats["total_carteiras"])
        s2.metric("Ativos cadastrados", stats["total_ativos"])
        s3.metric("Valor total alocado", f"R$ {stats['valor_total_alocado']:.2f}")

    st.divider()

    # =========================
    # Edição
    # =========================

    st.subheader("Editar dados")

    aba_dados, aba_senha, aba_carteiras, aba_conta = st.tabs(
        ["Dados pessoais", "Alterar senha", "Carteiras", "Excluir conta"]
    )

    # --- Dados pessoais ---
    with aba_dados:
        with st.form("form_editar_dados"):
            novo_nome = st.text_input("Nome", value=dados["nome"])
            novo_email = st.text_input("E-mail", value=dados["email"])

            salvar = st.form_submit_button("Salvar alterações")

        if salvar:
            erro = None

            if novo_nome.strip() != dados["nome"]:
                resultado = atualizar_nome(usuario_id, novo_nome)
                if not resultado["ok"]:
                    erro = resultado["erro"]

            if not erro and novo_email.strip().lower() != dados["email"]:
                resultado = atualizar_email(usuario_id, novo_email)
                if not resultado["ok"]:
                    erro = resultado["erro"]

            if erro:
                st.error(erro)
            else:
                st.session_state["usuario"]["nome"] = novo_nome.strip()
                st.session_state["usuario"]["email"] = novo_email.strip().lower()
                st.success("Dados atualizados com sucesso!")
                st.rerun()

    # --- Senha ---
    with aba_senha:
        with st.form("form_alterar_senha"):
            senha_atual = st.text_input("Senha atual", type="password")
            nova_senha = st.text_input("Nova senha", type="password")
            confirmar_senha = st.text_input("Confirmar nova senha", type="password")

            alterar = st.form_submit_button("Alterar senha")

        if alterar:
            if not senha_atual or not nova_senha:
                st.warning("Preencha todos os campos.")
            elif nova_senha != confirmar_senha:
                st.warning("As senhas não coincidem.")
            else:
                resultado = atualizar_senha(usuario_id, senha_atual, nova_senha)
                if resultado["ok"]:
                    st.success("Senha alterada com sucesso!")
                else:
                    st.error(resultado["erro"])
    # --- Carteiras ---
    with aba_carteiras:
        carteiras = listar_carteiras(usuario_id)

        if not carteiras:
            st.caption("Você ainda não tem nenhuma carteira criada.")
        else:
            for c in carteiras:
                with st.form(f"form_renomear_{c['id']}"):
                    col_nome, col_btn = st.columns([3, 1])

                    with col_nome:
                        novo_nome_carteira = st.text_input(
                            "Nome da carteira",
                            value=c["nome"],
                            key=f"nome_carteira_{c['id']}",
                            label_visibility="collapsed",
                        )

                    with col_btn:
                        salvar_carteira = st.form_submit_button(
                            "Salvar", use_container_width=True
                        )

                if salvar_carteira:
                    if novo_nome_carteira.strip() == c["nome"]:
                        st.caption("Nenhuma alteração.")
                    else:
                        resultado = renomear_carteira(c["id"], novo_nome_carteira)
                        if resultado["ok"]:
                            st.success(
                                f"Carteira renomeada para '{novo_nome_carteira.strip()}'."
                            )
                            st.rerun()
                        else:
                            st.error(resultado["erro"])

    # --- Excluir conta ---
    with aba_conta:
        st.warning(
            "Esta ação é irreversível: todas as suas carteiras e ativos "
            "serão excluídos permanentemente."
        )

        with st.form("form_excluir_conta"):
            senha_confirmacao = st.text_input(
                "Digite sua senha para confirmar", type="password"
            )
            excluir = st.form_submit_button("🗑️ Excluir minha conta")

        if excluir:
            if not senha_confirmacao:
                st.warning("Informe sua senha.")
            else:
                resultado = excluir_usuario(usuario_id, senha_confirmacao)
                if resultado["ok"]:
                    del st.session_state["usuario"]
                    st.success("Conta excluída. Até logo!")
                    st.rerun()
                else:
                    st.error(resultado["erro"])


# =========================
# Execução da página
# =========================

usuario = st.session_state.get("usuario")

if not usuario:
    st.warning("Você precisa fazer login para acessar seu perfil.")
    st.stop()

render_perfil(usuario["id"])
