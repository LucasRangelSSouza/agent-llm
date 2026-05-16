import streamlit as st

def render_sidebar(toolkits, rag_files):
    st.sidebar.header("Toolkits disponíveis")
    for toolkit_name, funcs in toolkits.items():
        st.sidebar.markdown(f"**{toolkit_name}**")
        st.sidebar.write(", ".join(funcs) if funcs else "Nenhuma função detectada.")
    st.sidebar.markdown("---")

    st.sidebar.header("Arquivos RAG disponíveis")
    if rag_files:
        arquivos_formatados = [caminho.replace("agent/knowledge/", "") for caminho in rag_files]
        st.sidebar.write(", ".join(arquivos_formatados))
    else:
        st.sidebar.write("Nenhum arquivo RAG encontrado.")
    st.sidebar.markdown("---")
