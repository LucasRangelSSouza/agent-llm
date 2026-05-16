import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

import httpx
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_unstructured import UnstructuredLoader
import boto3

import config as settings
from agent.memory import auto_memory
from agent.tools.artifact_store import artifact_summary_text, save_document_artifact


logger = logging.getLogger(__name__)
_EMBEDDINGS_CACHE = {}
_EMBEDDINGS_LOCK = Lock()


def _cached_embeddings(model_name: str):
    with _EMBEDDINGS_LOCK:
        if model_name not in _EMBEDDINGS_CACHE:
            _EMBEDDINGS_CACHE[model_name] = HuggingFaceEmbeddings(model_name=model_name)
        return _EMBEDDINGS_CACHE[model_name]


class DocumentProcessingToolkit:
    """
    RAG sob demanda para arquivos anexados ou caminhos informados pelo agente.

    Nao existe mais RAG automatico no boot: esta tool so roda quando o agente
    decidir chama-la.
    """

    def __init__(
        self,
        ai_service: Optional[dict] = None,
        default_file_paths: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        module_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        **_: Any,
    ) -> None:
        self.ai_service = ai_service
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.user_id = user_id
        self.module_name = module_name
        self.agent_name = agent_name
        model_name = settings.MODEL_EMBBEDINGS_RAG or "sentence-transformers/all-MiniLM-L6-v2"
        self.embeddings = _cached_embeddings(model_name)
        self.llm = auto_memory.build_llm(ai_service)
        if not self.llm:
            raise ValueError("Nao foi possivel inicializar LLM para processar documentos.")
        self.index_root = Path(getattr(settings, "RAG_UPLOADS_DIR", settings.UPLOADS_DIR)) / "document_indexes"
        self.index_root.mkdir(parents=True, exist_ok=True)
        self.cache_root = Path(getattr(settings, "RAG_UPLOADS_DIR", settings.UPLOADS_DIR)) / "document_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.default_file_paths = [str(path) for path in (default_file_paths or []) if path]
        self._last_file_paths: List[str] = []

    def query_documents(self):
        def _tool(
            query: str,
            files: Optional[Any] = None,
            uploaded_files: Optional[Any] = None,
            file_paths: Optional[Any] = None,
            max_chunks: int = 12,
        ) -> str:
            try:
                paths = self._resolve_file_paths(files=files, uploaded_files=uploaded_files, file_paths=file_paths)
                if not paths:
                    return self._json({"success": False, "error": "Nenhum arquivo valido foi recebido."})

                self._last_file_paths = paths
                docs = self._extract_documents(paths)
                chunks = self._split_documents(docs)
                answer = self._run_rag(query=query, file_paths=paths, max_chunks=max_chunks, chunks=chunks)
                artifact = save_document_artifact(
                    tenant_id=getattr(self, "tenant_id", None),
                    user_id=getattr(self, "user_id", None),
                    chat_id=getattr(self, "session_id", None),
                    module_name=getattr(self, "module_name", None),
                    agent_name=getattr(self, "agent_name", None),
                    label=f"{getattr(self, 'agent_name', 'document')}_document",
                    content={
                        "document_summary": answer,
                        "answer": answer,
                        "query": query,
                        "files": [Path(path).name for path in paths],
                        "source_paths": paths,
                        "chunks": [
                            {
                                "text": doc.page_content,
                                "metadata": doc.metadata,
                            }
                            for doc in chunks
                        ],
                    },
                    source_tool="document_processing_toolkit.query_documents",
                    source_type="document_rag",
                    metadata={"max_chunks": max_chunks},
                )
                return self._json(
                    {
                        "success": True,
                        "answer": answer,
                        "files": [Path(path).name for path in paths],
                        "artifact": artifact,
                        "artifact_summary": artifact_summary_text(artifact),
                    }
                )
            except Exception as exc:
                logger.exception("Erro ao processar documentos.")
                return self._json({"success": False, "error": str(exc)})

        return _tool

    def _resolve_file_paths(self, files: Any = None, uploaded_files: Any = None, file_paths: Any = None) -> List[str]:
        candidates = []
        candidates.extend(self._extract_paths(file_paths))
        candidates.extend(self._extract_paths(uploaded_files))
        candidates.extend(self._extract_paths(files))
        if not candidates:
            candidates.extend(self._last_file_paths)
        if not candidates:
            candidates.extend(self.default_file_paths)

        valid = []
        seen = set()
        for path in candidates:
            clean_path = str(path or "").strip()
            if not clean_path or clean_path in seen:
                continue
            local_path = self._ensure_local_file(clean_path)
            if local_path and Path(local_path).exists():
                seen.add(clean_path)
                valid.append(local_path)
        return valid

    def _ensure_local_file(self, path: str) -> Optional[str]:
        if path.startswith("s3://"):
            return self._download_s3_to_cache(path)
        if path.startswith("http://") or path.startswith("https://"):
            return self._download_http_to_cache(path)
        return path

    def _download_s3_to_cache(self, s3_path: str) -> str:
        bucket, key = self._parse_s3_path(s3_path)
        digest = hashlib.sha256(s3_path.encode("utf-8")).hexdigest()
        suffix = Path(key).suffix or ".bin"
        local_path = self.cache_root / f"{digest}{suffix}"
        if local_path.exists():
            return str(local_path)

        session = boto3.session.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        client = session.client("s3")
        with local_path.open("wb") as output:
            client.download_fileobj(bucket, key, output)
        return str(local_path)

    def _parse_s3_path(self, s3_path: str) -> tuple[str, str]:
        clean = s3_path.replace("s3://", "", 1)
        bucket, key = clean.split("/", 1)
        return bucket, key

    def _download_http_to_cache(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        suffix = Path(url.split("?", 1)[0]).suffix or ".bin"
        local_path = self.cache_root / f"{digest}{suffix}"
        if local_path.exists():
            return str(local_path)

        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            local_path.write_bytes(response.content)
        return str(local_path)

    def _extract_paths(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") or text.startswith("{"):
                try:
                    return self._extract_paths(json.loads(text))
                except Exception:
                    return [text]
            return [text]
        if isinstance(value, dict):
            if "uploaded_files" in value:
                return self._extract_paths(value.get("uploaded_files"))
            if "files" in value:
                return self._extract_paths(value.get("files"))
            return [value.get("filepath") or value.get("path") or value.get("file_path") or ""]
        if isinstance(value, Iterable):
            paths = []
            for item in value:
                paths.extend(self._extract_paths(item))
            return paths
        return []

    def _run_rag(self, query: str, file_paths: List[str], max_chunks: int, chunks: Optional[List[Any]] = None) -> str:
        vectorstore = self._load_or_build_index(file_paths, chunks=chunks)
        docs = vectorstore.similarity_search(query, k=max(1, min(int(max_chunks or 12), 40)))
        context = "\n\n".join(doc.page_content for doc in docs)
        prompt = ChatPromptTemplate.from_template(
            """
Voce e um especialista em analise de documentos.
Responda somente com base no contexto dos arquivos.
Se a resposta nao estiver no contexto, diga que nao encontrou a informacao.

CONTEXTO:
{context}

PERGUNTA:
{question}
"""
        )
        response = self.llm.invoke(prompt.format_messages(context=context, question=query))
        return (getattr(response, "content", None) or str(response)).strip()

    def _load_or_build_index(self, file_paths: List[str], chunks: Optional[List[Any]] = None):
        fingerprint = self._fingerprint(file_paths)
        index_dir = self.index_root / fingerprint
        if index_dir.exists():
            try:
                return FAISS.load_local(
                    index_dir.as_posix(),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
            except Exception:
                logger.warning("Falha ao carregar indice FAISS; reconstruindo.")

        docs = list(chunks or self._split_documents(self._extract_documents(file_paths)))
        if not docs:
            raise ValueError("Nenhum conteudo foi extraido dos arquivos.")

        vectorstore = FAISS.from_documents(docs, self.embeddings)
        index_dir.mkdir(parents=True, exist_ok=True)
        vectorstore.save_local(index_dir.as_posix())
        return vectorstore

    def _extract_documents(self, file_paths: List[str]) -> List[Any]:
        docs = []
        for path in file_paths:
            docs.extend(UnstructuredLoader(path).load())
        return docs

    def _split_documents(self, docs: List[Any]) -> List[Any]:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
        return splitter.split_documents(docs)

    def _fingerprint(self, file_paths: List[str]) -> str:
        payload = []
        for path in sorted(file_paths):
            item = Path(path)
            stat = item.stat()
            payload.append({"path": str(item.resolve()), "size": stat.st_size, "mtime": int(stat.st_mtime)})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _json(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)
