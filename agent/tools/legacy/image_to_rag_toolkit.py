import logging
from pathlib import Path
from typing import Dict, List, Optional

from agent.tools.image_rag_tool import ImageRagTool


logger = logging.getLogger(__name__)


class ImageToRAGToolKit:
    """
    Toolkit que combina OCR + visão computacional + RAG com PDF técnico fixo.
    O provider de IA é resolvido a partir do template ativo, sem depender de .env.
    """

    def __init__(self, ai_service=None):
        self.ai_service = ai_service
        self.tool = ImageRagTool(ai_service=ai_service)
        self.reference_pdf = Path("agent/knowledge/imagens/CNH.pdf").as_posix()

        if not Path(self.reference_pdf).exists():
            logger.warning("PDF de referência não encontrado: %s", self.reference_pdf)

        logger.info("ImageToRAGToolKit inicializado com sucesso.")

    def make_tool_from_uploaded(self):
        def _tool(query: str, files: List[Dict]):
            try:
                image_path: Optional[str] = None

                for file in files or []:
                    filepath = file.get("filepath")
                    filetype = file.get("type", "")
                    filename = file.get("filename", "desconhecido")

                    if not filepath or not Path(filepath).exists():
                        logger.warning("Arquivo ignorado (não encontrado): %s", filename)
                        continue

                    if "image" in filetype or str(filepath).lower().endswith((".jpg", ".jpeg", ".png")):
                        image_path = filepath
                        logger.info("Imagem identificada: %s", filename)

                if not image_path:
                    return {
                        "content": "Nenhuma imagem válida foi encontrada entre os arquivos enviados.",
                        "role": "assistant",
                        "name": "image_rag_agent",
                        "terminate": True,
                    }

                if not Path(self.reference_pdf).exists():
                    return {
                        "content": f"Arquivo PDF de referência não encontrado: {self.reference_pdf}",
                        "role": "assistant",
                        "name": "image_rag_agent",
                        "terminate": True,
                    }

                response = self.tool._run(
                    query,
                    image_path=image_path,
                    pdf_path=self.reference_pdf,
                )

                return {
                    "content": response,
                    "role": "assistant",
                    "name": "image_rag_agent",
                    "terminate": True,
                }

            except Exception as exc:
                logger.error("Erro no ImageRag dinâmico: %s", exc, exc_info=True)
                return {
                    "content": f"Erro ao processar ImageRag: {exc}",
                    "role": "assistant",
                    "name": "image_rag_agent",
                    "terminate": True,
                }

        return _tool
