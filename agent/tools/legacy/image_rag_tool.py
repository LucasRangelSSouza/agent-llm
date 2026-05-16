from pathlib import Path
from typing import Optional, Type

import pdfplumber
import pytesseract
import torch
from PIL import Image
from pdf2image import convert_from_path
from pydantic import BaseModel, Field
from transformers import BlipForConditionalGeneration, BlipProcessor

import config as settings
from agent.memory.auto_memory import build_llm
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_text_splitters import RecursiveCharacterTextSplitter


class ImageRagToolInput(BaseModel):
    question: str = Field(description="Pergunta sobre a peça contida na imagem.")
    image_path: str = Field(description="Caminho para a imagem da peça.")
    pdf_path: str = Field(description="Caminho para o arquivo PDF com a base de referência.")


class ImageRagTool:
    """Tool que combina visão computacional + RAG em PDF."""

    name: str = "ImageRagTool"
    description: str = "Identifica uma peça em uma imagem e responde tecnicamente usando um PDF como base."
    args_schema: Type[BaseModel] = ImageRagToolInput

    def __init__(self, ai_service=None):
        self.ai_service = ai_service
        embedding_model = getattr(settings, "MODEL_EMBBEDINGS_RAG", "") or "sentence-transformers/all-MiniLM-L6-v2"
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)

    def _run(self, question: str, image_path: str, pdf_path: str) -> str:
        pdf_path = Path(pdf_path).as_posix()

        try:
            image = Image.open(image_path).convert("RGB")
            processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
            model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
            inputs = processor(image, return_tensors="pt")
            with torch.no_grad():
                output = model.generate(**inputs)
            caption = processor.decode(output[0], skip_special_tokens=True)
        except Exception as exc:
            return f"Erro ao processar imagem: {exc}"

        full_question = f"{question}. A imagem mostra: {caption}"

        raw_text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                raw_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
        except Exception:
            raw_text = ""

        if not raw_text.strip():
            try:
                pages = convert_from_path(pdf_path)
                ocr_texts = [pytesseract.image_to_string(page) for page in pages]
                raw_text = "\n".join(filter(None, ocr_texts)).strip()
            except Exception as exc:
                return f"Falha ao extrair texto do PDF: {exc}"

        if not raw_text.strip():
            return "Nenhum conteúdo textual encontrado no PDF."

        splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
        chunks = splitter.split_text(raw_text)
        if not chunks:
            return "O texto do PDF não pôde ser segmentado em partes consultáveis."

        try:
            vectorstore = FAISS.from_texts(chunks, embedding=self.embeddings)
        except Exception as exc:
            return f"Erro ao criar índice vetorial FAISS: {exc}"

        relevant_docs = vectorstore.similarity_search(full_question, k=4)
        if not relevant_docs:
            return "Nenhum conteúdo relevante foi encontrado no PDF para essa pergunta."

        context_text = "\n\n".join([doc.page_content for doc in relevant_docs])
        prompt_template = """
Você é um assistente técnico especialista em projetos mecânicos.
Use APENAS o contexto abaixo para responder à pergunta de forma clara e precisa.

Contexto:
{context}

Pergunta:
{question}

Resposta:
"""
        prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
        llm = build_llm(self.ai_service)
        if llm is None:
            return "Nenhum serviço de IA válido foi configurado no template para o ImageRagTool."

        rag_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | RunnableLambda(lambda data: prompt.format(context=data["context"], question=data["question"]))
            | llm
        )

        result = rag_chain.invoke({"context": context_text, "question": full_question})
        if hasattr(result, "content"):
            return str(result.content).strip()
        return str(result).strip()
