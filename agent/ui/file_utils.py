import json
import streamlit as st
from agent.ui.constants import JSON_PATH
from pathlib import Path
def load_json():
    if not JSON_PATH.exists():
        st.error(f"Arquivo não encontrado: {JSON_PATH}")
        st.stop()
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(json_path: Path, data: dict, do_rerun: bool = True):
    """
    Salva o JSON e, opcionalmente, força o Streamlit a recarregar.
    """
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        st.success(f"Arquivo salvo com sucesso em: {json_path}")
        if do_rerun:
            st.rerun()

    except Exception as e:
        st.error(f"Erro ao salvar o JSON: {e}")
