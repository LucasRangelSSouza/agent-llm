import os
import pdfplumber
import docx
import pytesseract
from PIL import Image
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


class DocumentComparatorToolkit:
    """
    Toolkit para comparar dois documentos (PDF, DOCX ou imagem)
    e retornar uma resposta padronizada compatível com agentes AutoGen.
    """

    def __init__(self):
        pass

    # =============================== #
    # 🔍 Lógica principal
    # =============================== #
    def _compare_logic(self, file_path_1: str, file_path_2: str):
        if not os.path.exists(file_path_1) or not os.path.exists(file_path_2):
            return self._format_output(
                "❌ Erro: Um ou ambos os caminhos de arquivo não existem."
            )

        logger.info(f"📂 Comparando arquivos: {file_path_1} vs {file_path_2}")

        text1 = self._extract_text(file_path_1)
        text2 = self._extract_text(file_path_2)

        if not text1.strip() or not text2.strip():
            return self._format_output(
                "⚠️ Um ou ambos os documentos não puderam ser processados (sem texto extraído)."
            )

        # Calcula similaridade
        ratio = SequenceMatcher(None, text1, text2).ratio()
        percentual = ratio * 100

        # Calcula diferenças
        diff_text, total_changes = self._compute_diff(text1, text2)

        # Construção do texto final
        resumo = (
            f"📊 Similaridade textual: **{percentual:.2f}%**\n"
            f"🔍 Foram detectadas {total_changes} alterações relevantes entre os dois textos.\n"
        )

        if total_changes == 0:
            resumo += "✅ Os documentos são praticamente idênticos.\n"
        elif total_changes <= 5:
            resumo += "🟡 As diferenças são pequenas, indicando revisões pontuais.\n"
        else:
            resumo += "🔴 Há várias diferenças, indicando versões distintas ou edições substanciais.\n"

        content = f"{resumo}\n\n🧩 Diferenças encontradas (máx. 10):\n{diff_text}"

        return self._format_output(content)

    # =============================== #
    # 🧩 Funções auxiliares
    # =============================== #
    def _extract_text(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext == ".pdf":
                with pdfplumber.open(file_path) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
            elif ext == ".docx":
                doc = docx.Document(file_path)
                return "\n".join(p.text for p in doc.paragraphs)
            elif ext in [".jpg", ".jpeg", ".png"]:
                return pytesseract.image_to_string(Image.open(file_path))
            else:
                logger.warning(f"⚠️ Tipo de arquivo não suportado: {ext}")
                return ""
        except Exception as e:
            logger.error(f"Erro ao processar arquivo {file_path}: {e}")
            return ""

    def _compute_diff(self, text1: str, text2: str):
        seqm = SequenceMatcher(None, text1, text2)
        diffs = []
        total_changes = 0

        for tag, i1, i2, j1, j2 in seqm.get_opcodes():
            if tag != "equal":
                total_changes += 1
                trecho1 = text1[i1:i2].strip().replace("\n", " ")
                trecho2 = text2[j1:j2].strip().replace("\n", " ")
                diffs.append(
                    f"{tag.upper()}:\n"
                    f"- Documento 1: {trecho1[:400]}\n"
                    f"- Documento 2: {trecho2[:400]}"
                )

        if not diffs:
            return ("Nenhuma diferença relevante encontrada.", 0)

        return ("\n\n".join(diffs[:10]), total_changes)

    def _format_output(self, content: str):
        """Retorna no formato esperado pelo agente."""
        return {
            "content": content.strip(),
            "role": "assistant",
            "name": "compare_agent",
            "terminate": True,
        }

    # =============================== #
    # 🧠 Tool pronta pra registrar no agente
    # =============================== #
    def make_tool(self):
        """
        Tool pronta para uso no AutoGen.
        Sempre usa modo full e formato padronizado.
        """
        def compare_docs(file_path_1: str, file_path_2: str):
            return self._compare_logic(file_path_1=file_path_1, file_path_2=file_path_2)

        return compare_docs


# =====================================================
# 🔧 Teste rápido
# =====================================================
if __name__ == "__main__":

    toolkit = DocumentComparatorToolkit()
    compare_tool = toolkit.make_tool()

    file1 = r"C:\Users\clovis.vieira\Downloads\documentos_teste\documentos_teste\doucumento_01.pdf"
    file2 = r"C:\Users\clovis.vieira\Downloads\documentos_teste\documentos_teste\documento_02.pdf"

    result = compare_tool(file_path_1=file1, file_path_2=file2)
    print("\n📄 RESULTADO (tool para agente):")
    print(result)
