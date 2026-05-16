from .constants import BASE_PATH

from pathlib import Path

def get_rag_files():
    # Se for S3: apenas retorna vazio (ou pré-carregados)
    if isinstance(BASE_PATH, str) and BASE_PATH.startswith("s3://"):
        # Usuário vai digitar manualmente e o URI vai direto para o JSON
        return []

    # Caso local (funciona igual antes)
    knowledge_path = Path(BASE_PATH) / "agent" / "knowledge"
    if not knowledge_path.exists():
        return []

    rag_files = []
    for subfolder in sorted(knowledge_path.iterdir()):
        if subfolder.is_dir():
            for file in sorted(subfolder.glob("*.*")):
                if file.suffix.lower() in [".txt", ".md", ".pdf", ".json", ".csv"]:
                    rel_path = f"agent/knowledge/{subfolder.name}/{file.name}"
                    rag_files.append(rel_path)
    return rag_files