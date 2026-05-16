import streamlit as st
from agent.ui.file_utils import save_json

def rag_file_selector_multiple(label, current_values, available_rags, key_prefix=""):
    st.markdown(f"**{label}**")

    # Selectbox múltiplo normal
    selected_from_list = st.multiselect(
        f"{label} (selecionar da lista)",
        options=available_rags,
        default=[r for r in current_values if r in available_rags],
        key=f"{key_prefix}_select"
    )

    # Campo de entrada manual (um por linha)
    manual_text = st.text_area(
        f"{label} (manual - um por linha)",
        value="\n".join([r for r in current_values if r not in available_rags]),
        height=100,
        key=f"{key_prefix}_manual"
    )

    manual_list = [
        line.strip()
        for line in manual_text.split("\n")
        if line.strip()
    ]

    return selected_from_list + manual_list



def render_db_connections(module_name, module_data, edited_data, json_path):
    """Renderiza a seção de conexões de banco de dados."""
    st.markdown("#### Configurações de Banco de Dados (DB_connections)")
    db_conns = module_data.get("DB_connections", {})
    new_db_conns = {}

    for conn_name, conn_info in list(db_conns.items()):
        with st.expander(f"Conexão: {conn_name}", expanded=False):
            new_conn_name = st.text_input(
                "Nome da conexão", value=conn_name, key=f"{module_name}_{conn_name}_name"
            )
            new_desc = st.text_input(
                "Descrição", value=conn_info.get("description", ""), key=f"{module_name}_{conn_name}_desc"
            )
            new_uri = st.text_input(
                "URI do banco", value=conn_info.get("uri", "sqlite:///:memory:"),
                key=f"{module_name}_{conn_name}_uri"
            )

            # --- Botão de exclusão da conexão ---
            if st.button(f"**Apagar conexão '{conn_name}'**", key=f"del_btn_{module_name}_{conn_name}"):
                del db_conns[conn_name]
                module_data["DB_connections"] = db_conns
                edited_data[module_name] = module_data
                save_json(json_path, edited_data, True)
                st.stop()

            new_db_conns[new_conn_name] = {"description": new_desc, "uri": new_uri}

    # Adicionar nova conexão
    with st.expander("**Adicionar nova conexão**", expanded=False):
        new_conn_name = st.text_input(f"Nome da nova conexão ({module_name})", key=f"new_conn_{module_name}")
        new_conn_desc = st.text_input(f"Descrição ({module_name})", key=f"new_desc_{module_name}")
        new_conn_uri = st.text_input(
            f"URI ({module_name})", "sqlite:///:memory:", key=f"new_uri_{module_name}"
        )

        if st.button(f"**Adicionar conexão ao módulo {module_name}**", key=f"add_conn_btn_{module_name}"):
            if new_conn_name:
                new_db_conns[new_conn_name] = {
                    "description": new_conn_desc,
                    "uri": new_conn_uri,
                }
                module_data["DB_connections"] = new_db_conns
                edited_data[module_name] = module_data
                save_json(json_path, edited_data, True)
            else:
                st.error("O nome da conexão é obrigatório.")

    module_data["DB_connections"] = new_db_conns


def render_agent_editor(module_name, module_data, edited_data, json_path, allowed_types, available_tools, rag_files):
    """Renderiza e edita os agentes dentro de um módulo."""
    st.markdown("#### Agentes (Submódulos)")
    submodules = module_data.get("submodules", {})

    for agent_name, agent_data in list(submodules.items()):
        with st.expander(f"Agente: {agent_name}", expanded=False):
            new_agent_name = st.text_input(
                "Nome do agente", value=agent_name, key=f"{module_name}_{agent_name}_name"
            )

            new_type = st.selectbox(
                "Tipo de agente",
                allowed_types,
                index=allowed_types.index(agent_data.get("type", allowed_types[0]))
                if agent_data.get("type") in allowed_types else 0,
                key=f"{module_name}_{agent_name}_type"
            )

            new_tools = st.multiselect(
                "Ferramentas (toolkits)",
                options=available_tools,
                default=[t for t in agent_data.get("tools", []) if t in available_tools],
                key=f"{module_name}_{agent_name}_tools"
            )

            new_prompt = st.text_area(
                "Prompt do agente",
                value=agent_data.get("prompt", ""),
                height=200,
                key=f"{module_name}_{agent_name}_prompt"
            )

            new_rags = rag_file_selector_multiple(
                label="Arquivos RAG",
                current_values=agent_data.get("rag_files", []),
                available_rags=rag_files,
                key_prefix=f"{module_name}_{agent_name}_rags"
            )
            # Interações entre agentes
            st.markdown("##### Interações permitidas (allowed_interactions)")
            all_agents = [a for a in submodules.keys() if a != agent_name]
            new_allowed = st.multiselect(
                f"Agentes que {agent_name} pode chamar",
                options=all_agents,
                default=[a for a in agent_data.get("allowed_interactions", []) if a in all_agents],
                key=f"{module_name}_{agent_name}_allowed"
            )

            # --- Botão de exclusão de agente ---
            if st.button(f"**Apagar agente '{agent_name}'**", key=f"del_agent_btn_{module_name}_{agent_name}"):
                del submodules[agent_name]
                module_data["submodules"] = submodules
                edited_data[module_name] = module_data
                save_json(json_path, edited_data, True)
                st.stop()

            # Atualiza agente se houver mudanças
            submodules[new_agent_name] = {
                "type": new_type,
                "tools": new_tools,
                "prompt": new_prompt,
                "rag_files": new_rags,
                "allowed_interactions": new_allowed,
            }

            if new_agent_name != agent_name:
                submodules.pop(agent_name)
                module_data["submodules"] = submodules
                edited_data[module_name] = module_data
                save_json(json_path, edited_data, True)

    # Adicionar novo agente
    with st.expander("**Adicionar novo agente**", expanded=False):
        new_agent_name = st.text_input(
            f"Nome do novo agente ({module_name})", key=f"new_agent_name_{module_name}"
        )
        if new_agent_name and not new_agent_name.endswith("_agent"):
            st.warning("O nome do agente deve terminar com '_agent'.")

        new_agent_type = st.selectbox(
            f"Tipo do novo agente ({module_name})", allowed_types, key=f"new_agent_type_{module_name}"
        )

        new_agent_tools = st.multiselect(
            f"Ferramentas do novo agente ({module_name})", options=available_tools, key=f"new_agent_tools_{module_name}"
        )

        new_agent_rags = st.multiselect(
            f"Arquivos RAG do novo agente ({module_name})", options=rag_files, key=f"new_agent_rags_{module_name}"
        )

        new_agent_prompt = st.text_area(
            f"Prompt do novo agente ({module_name})", "", height=180, key=f"new_agent_prompt_{module_name}"
        )

        if st.button(f"**Adicionar agente ao módulo {module_name}**", key=f"add_agent_btn_{module_name}"):
            if not new_agent_name:
                st.error("O nome do agente é obrigatório.")
            elif not new_agent_name.endswith("_agent"):
                st.error("O nome do agente deve terminar com '_agent'.")
            elif new_agent_name in submodules:
                st.error("Já existe um agente com esse nome neste módulo.")
            else:
                submodules[new_agent_name] = {
                    "type": new_agent_type,
                    "tools": new_agent_tools,
                    "prompt": new_agent_prompt,
                    "rag_files": new_agent_rags,
                    "allowed_interactions": [],
                }
                module_data["submodules"] = submodules
                edited_data[module_name] = module_data
                save_json(json_path, edited_data, True)

    module_data["submodules"] = submodules


def render_module_editor(module_name, module_data, edited_data, json_path, allowed_types, available_tools, rag_files):
    """Renderiza o editor completo de um módulo."""
    with st.expander(f"Módulo: {module_name}", expanded=False):
        new_module_name = st.text_input(
            "Nome do módulo", value=module_name, key=f"mod_name_{module_name}"
        )

        # --- Campo de descrição mestre ---
        descricao_mestre = module_data.get("descricao_mestre", "")
        nova_descricao_mestre = st.text_area(
            "📝 Descrição mestre do módulo (usada pelo orquestrador primário):",
            value=descricao_mestre,
            height=120,
            key=f"descricao_mestre_{module_name}"
        )

        if nova_descricao_mestre != descricao_mestre:
            module_data["descricao_mestre"] = nova_descricao_mestre
            edited_data[module_name] = module_data
            save_json(json_path, edited_data, True)
            st.success("Descrição mestre atualizada com sucesso!")

        render_db_connections(module_name, module_data, edited_data, json_path)
        render_agent_editor(module_name, module_data, edited_data, json_path, allowed_types, available_tools, rag_files)

        # --- Botão para excluir módulo inteiro ---
        st.markdown("---")
        if st.button(f"**Apagar módulo '{module_name}'**", key=f"del_mod_btn_{module_name}"):
            del edited_data[module_name]
            save_json(json_path, edited_data, True)
            st.stop()

        if new_module_name != module_name:
            edited_data[new_module_name] = edited_data.pop(module_name)
            save_json(json_path, edited_data, True)
            st.success(f"Módulo renomeado para '{new_module_name}' com sucesso!")


def render_new_module_form(edited_data, json_path, allowed_types, available_tools, rag_files):
    """Renderiza o formulário para adicionar um novo módulo."""
    st.markdown("### **Adicionar novo módulo**")

    with st.expander("**Novo módulo**", expanded=False):
        new_module_name = st.text_input("Nome do novo módulo", key="new_module_name")
        new_module_desc = st.text_area("Descrição mestre do módulo", "", key="new_module_desc")

        if st.button("**Adicionar módulo**", key="add_new_module_btn"):
            if not new_module_name:
                st.error("O nome do módulo é obrigatório.")
                return

            if new_module_name in edited_data:
                st.error("Já existe um módulo com esse nome.")
                return

            # Cria estrutura inicial do módulo com descricao_mestre
            edited_data[new_module_name] = {
                "descricao_mestre": new_module_desc,
                "DB_connections": {},
                "submodules": {}
            }

            save_json(json_path, edited_data, True)
            st.success(f"Módulo '{new_module_name}' adicionado com sucesso!")