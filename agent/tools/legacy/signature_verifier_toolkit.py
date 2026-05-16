import os
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Union
from sklearn.metrics.pairwise import cosine_similarity
from PIL import Image
from pdf2image import convert_from_path
from docx import Document


class SignatureAnalyzerToolkit:
    """
    Toolkit para identificar o autor provável de uma assinatura.
    Compara uma imagem enviada com a base local em `agent/knowledge/assinatura_referencia`.
    Retorna o nome do arquivo de referência (sem extensão) mais parecido.
    """

    def __init__(self, reference_dir: str = None):
        base_path = Path(__file__).resolve().parents[3]
        self.reference_dir = Path(reference_dir or base_path / "agent" / "knowledge" / "assinatura_referencia")
        self.image_size = (220, 155)
        self.extensoes_suportadas = [".png", ".jpg", ".jpeg"]

    # ==========================================================
    # 🧩 Funções auxiliares
    # ==========================================================
    def _preprocess_signature_from_image(self, img: np.ndarray) -> np.ndarray:
        img = cv2.resize(img, self.image_size)
        _, img_bin = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
        return img_bin.flatten().reshape(1, -1)

    def _load_image_from_path(self, path: Path) -> np.ndarray:
        """Carrega imagem a partir de um arquivo (ou página de PDF)."""
        ext = path.suffix.lower()
        if ext in [".png", ".jpg", ".jpeg"]:
            return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        elif ext == ".pdf":
            pages = convert_from_path(str(path))
            img = np.array(pages[0])
            return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        elif ext == ".docx":
            doc = Document(str(path))
            texto = "\n".join([p.text for p in doc.paragraphs])
            raise ValueError("❌ O arquivo DOCX não contém imagem para assinatura.")
        else:
            raise ValueError(f"⚠️ Tipo de arquivo não suportado: {ext}")

    def _compare_with_references(self, input_img: np.ndarray) -> Dict[str, Union[str, float]]:
        """Compara uma imagem de assinatura com as referências locais."""
        if not self.reference_dir.exists():
            return {"erro": f"❌ Pasta de referência '{self.reference_dir}' não existe."}

        arquivos_ref = list(self.reference_dir.glob("*"))
        if not arquivos_ref:
            return {"erro": f"⚠️ Nenhuma assinatura encontrada em {self.reference_dir}"}

        input_vector = self._preprocess_signature_from_image(input_img)
        best_score = 0
        best_match = None

        for ref_file in arquivos_ref:
            try:
                ref_img = cv2.imread(str(ref_file), cv2.IMREAD_GRAYSCALE)
                if ref_img is None:
                    continue
                ref_vector = self._preprocess_signature_from_image(ref_img)
                score = cosine_similarity(input_vector, ref_vector)[0][0]
                if score > best_score:
                    best_score = score
                    best_match = ref_file.stem  # nome sem extensão
            except Exception as e:
                print(f"[WARNING] Erro ao processar {ref_file.name}: {e}")
                continue

        return {"assinante": best_match, "similaridade": round(float(best_score), 4)}

    # ==========================================================
    # 🧠 Função principal (modo agente)
    # ==========================================================
    def _analisar(self, file_path: str):
        try:
            img = self._load_image_from_path(Path(file_path))
            resultado = self._compare_with_references(img)

            if "erro" in resultado:
                return self._format_output(resultado["erro"])

            if not resultado["assinante"]:
                return self._format_output("⚠️ Nenhuma correspondência encontrada.")

            assinante = resultado["assinante"]
            score = resultado["similaridade"]

            mensagem = (
                f"🖋️ A assinatura corresponde provavelmente a **{assinante}** "
                f"(similaridade: {score:.2f})."
            )
            return self._format_output(mensagem)

        except Exception as e:
            return self._format_output(f"❌ Erro ao processar a imagem: {e}")

    def _format_output(self, content: str):
        """Retorno padrão compatível com agentes AutoGen."""
        return {
            "content": content.strip(),
            "role": "assistant",
            "name": "signature_agent",
            "terminate": True,
        }

    # ==========================================================
    # 🔗 Tool compatível com AutoGen
    # ==========================================================
    def make_tool(self):
        """
        Retorna uma função pronta para ser registrada no agente.
        Exemplo: signature_tool(file_path='uploads/assinatura.png')
        """
        def _tool(file_path: str):
            return self._analisar(file_path)
        return _tool


# ==========================================================
# 🧪 Teste local
# ==========================================================
if __name__ == "__main__":
    toolkit = SignatureAnalyzerToolkit()
    analyze_signature = toolkit.make_tool()

    file = r"C:\Users\clovis.vieira\Downloads\documentos_teste\documentos_teste\philippe_petersen.jpeg"
    result = analyze_signature(file)
    print(result)
