import streamlit as st

from agent.ui.ui_module_editor import render_module_editor, render_new_module_form
from agent.ui.ui_sidebar import render_sidebar
from agent.ui.constants import ALLOWED_TYPES
from agent.ui.file_utils import JSON_PATH, load_json, save_json

from agent.ui.toolkit_loader import get_toolkits_with_functions
from agent.ui.rag_loader import get_rag_files


# === Configuração da página ===
st.set_page_config(page_title="Agent Config Editor", layout="wide")
st.title("Painel de Configuração Agent")

# === Carrega os dados do JSON ===
edited_data = load_json()

# === Carrega toolkits e RAGs ===
toolkits = get_toolkits_with_functions()
available_tools = [
    f"{tk}.{func}" for tk, funcs in toolkits.items()
    for func in funcs if not func.startswith("Erro")
]
rag_files = get_rag_files()

# === Renderiza a sidebar ===
render_sidebar(toolkits, rag_files)



# === Renderiza cada módulo do JSON ===
for module_name, module_data in list(edited_data.items()):
    render_module_editor(
        module_name=module_name,
        module_data=module_data,
        edited_data=edited_data,
        json_path=JSON_PATH,
        allowed_types=ALLOWED_TYPES,
        available_tools=available_tools,
        rag_files=rag_files
    )

# === Adicionar novo módulo ===
render_new_module_form(
    edited_data=edited_data,
    json_path=JSON_PATH,
    allowed_types=ALLOWED_TYPES,
    available_tools=available_tools,
    rag_files=rag_files
)

# === Botão global de salvar todas as modificações ===
st.markdown("---")
if st.button("**Salvar todas as modificações**", type="primary", use_container_width=True):
    save_json(JSON_PATH, edited_data, do_rerun=True)

st.markdown("---")