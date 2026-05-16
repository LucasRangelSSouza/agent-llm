import os
import logging
import json
import hashlib
import shutil
import time
from typing import List, TypedDict
from pathlib import Path
from threading import Lock

# LangChain / LangGraph imports
from langchain_unstructured import UnstructuredLoader as UnstructuredFileLoader

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import START, StateGraph
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
import config as settings
import boto3
from agent.memory import auto_memory

logger = logging.getLogger(__name__)
_EMBEDDINGS_CACHE = {}
_EMBEDDINGS_LOCK = Lock()


def get_cached_embeddings(model_name: str):
    with _EMBEDDINGS_LOCK:
        cached = _EMBEDDINGS_CACHE.get(model_name)
        if cached is None:
            cached = HuggingFaceEmbeddings(model_name=model_name)
            _EMBEDDINGS_CACHE[model_name] = cached
        return cached

# ==========================================================
# 🔧 CORREÇÃO COMPLETA DO DOWNLOAD DO S3 (FUNCIONA NO WINDOWS)
# ==========================================================
def parse_s3_path(s3_path: str) -> tuple[str, str]:
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Caminho S3 inválido: {s3_path}")

    no_prefix = s3_path.replace("s3://", "", 1)

    # separa: bucket / key
    parts = no_prefix.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Caminho S3 mal formatado: {s3_path}")

    return parts[0], parts[1]


# ==========================================================
# RAG TOOLKIT
# ==========================================================
def _callable_name(func) -> str:
    return getattr(func, "__name__", repr(func))


class RAGToolKit:
    def __init__(self, ai_service=None):
        self.ai_service = ai_service

        # Embeddings locais evitam acoplamento com provider específico.
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.MODEL_EMBBEDINGS_RAG or "sentence-transformers/all-MiniLM-L6-v2"
        )

        self.llm = auto_memory.build_llm(ai_service)
        if not self.llm:
            raise ValueError("Não foi possível inicializar o modelo de linguagem para o RAG.")

        self._s3_client = None
        base_dir = getattr(settings, "PERSISTENT_MEMORY_INDEX_PATH", "") or "agent/rag_indexes"
        self.faiss_root_dir = Path(base_dir)
        self.faiss_root_dir.mkdir(parents=True, exist_ok=True)
        self.rag_cache_dir = Path(getattr(settings, "RAG_UPLOADS_DIR", settings.UPLOADS_DIR)) / "rag_cache"
        self.rag_cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_uploaded_file_paths: List[str] = []
        self.s3_persistence_base = getattr(
            settings,
            "RAG_FAISS_S3_PATH",
            "s3://agent-core-quality-digital-financas-prod/multimedia/rag_faisss_perrsistence/faiss_finances/",
        ) or ""
        self._s3_persistence_bucket = None
        self._s3_persistence_key = None
        if self.s3_persistence_base:
            try:
                bucket, key = parse_s3_path(self.s3_persistence_base)
                self._s3_persistence_bucket = bucket
                self._s3_persistence_key = key.rstrip("/")
            except ValueError as exc:
                logger.warning(f"Caminho S3 de persistência inválido: {exc}")
                self.s3_persistence_base = ""

        logger.info("✅ RAGToolKitLangGraph inicializado com sucesso.")

    def _get_s3_client(self):
        if self._s3_client is None:
            session = boto3.session.Session(
                region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            )
            self._s3_client = session.client("s3")
        return self._s3_client

    def _file_fingerprint(self, fp: str) -> str:
        try:
            if fp.startswith("s3://"):
                bucket, key = parse_s3_path(fp)
                try:
                    head = self._get_s3_client().head_object(Bucket=bucket, Key=key)
                    etag = (head.get("ETag") or "").strip('"')
                    size = head.get("ContentLength", "")
                    last_modified = head.get("LastModified")
                    lm_str = last_modified.isoformat() if last_modified else ""
                    return f"s3|{bucket}|{key}|{etag}|{size}|{lm_str}"
                except Exception as e:
                    logger.warning(f"Falha no head_object do S3 (fingerprint): {e}")
                    return f"s3|{bucket}|{key}"
            else:
                p = Path(fp)
                try:
                    st = p.stat()
                    return f"local|{p.resolve()}|{int(st.st_mtime)}|{st.st_size}"
                except Exception:
                    return f"local|{fp}"
        except Exception:
            return f"raw|{fp}"

    def _build_corpus_manifest(self, file_paths: List[str]) -> dict:
        files = []
        for fp in file_paths:
            files.append({"source": fp, "fingerprint": self._file_fingerprint(fp)})
        files_sorted = sorted(files, key=lambda x: x["source"])
        payload = {"files": files_sorted}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        payload["corpus_fingerprint"] = digest
        return payload

    def _faiss_index_dir(self, corpus_fingerprint: str) -> Path:
        return self.faiss_root_dir / corpus_fingerprint

    def _load_faiss_index(self, index_dir: Path, manifest: dict):
        manifest_path = index_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Falha ao ler manifest FAISS: {e}")
            return None

        if saved.get("corpus_fingerprint") != manifest.get("corpus_fingerprint"):
            return None
        if saved.get("files") != manifest.get("files"):
            return None

        try:
            return FAISS.load_local(
                index_dir.as_posix(),
                self.embeddings,
                allow_dangerous_deserialization=True,
            )
        except Exception as e:
            logger.warning(f"Falha ao carregar FAISS local: {e}")
            return None

    def _save_faiss_index(self, index_dir: Path, vectorstore, manifest: dict) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        vectorstore.save_local(index_dir.as_posix())
        manifest_path = index_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _cached_s3_local_path(self, s3_path: str) -> Path:
        bucket, key = parse_s3_path(s3_path)
        digest = hashlib.sha256(f"s3|{bucket}|{key}".encode("utf-8")).hexdigest()
        suffix = Path(key).suffix or ".bin"
        return self.rag_cache_dir / f"{digest}{suffix}"

    def _ensure_s3_cached(self, s3_path: str) -> Path:
        bucket, key = parse_s3_path(s3_path)
        local_path = self._cached_s3_local_path(s3_path)
        meta_path = local_path.with_suffix(local_path.suffix + ".json")

        current_meta = None
        try:
            head = self._get_s3_client().head_object(Bucket=bucket, Key=key)
            etag = (head.get("ETag") or "").strip('"')
            size = head.get("ContentLength", "")
            last_modified = head.get("LastModified")
            lm_str = last_modified.isoformat() if last_modified else ""
            current_meta = {
                "bucket": bucket,
                "key": key,
                "etag": etag,
                "size": size,
                "last_modified": lm_str,
            }
        except Exception as e:
            logger.warning(f"Falha no head_object do S3 (cache local): {e}")

        if local_path.exists() and meta_path.exists() and current_meta:
            try:
                saved = json.loads(meta_path.read_text(encoding="utf-8"))
                if saved == current_meta:
                    return local_path
            except Exception as e:
                logger.warning(f"Falha ao ler metadata do cache local: {e}")

        if local_path.exists() and not current_meta:
            return local_path

        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as f:
            self._get_s3_client().download_fileobj(bucket, key, f)

        if current_meta:
            meta_path.write_text(
                json.dumps(current_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return local_path

    def _is_s3_persistence_enabled(self) -> bool:
        return bool(self._s3_persistence_bucket and self._s3_persistence_key)

    def _s3_index_location(self, corpus_fingerprint: str) -> tuple[str, str]:
        base_key = (self._s3_persistence_key or "").strip("/")
        prefix = f"{base_key}/{corpus_fingerprint}/" if base_key else f"{corpus_fingerprint}/"
        return self._s3_persistence_bucket, prefix

    def _list_s3_index_objects(self, bucket: str, prefix: str) -> List[dict]:
        client = self._get_s3_client()
        objects = []
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                objects.extend(page.get("Contents", []))
        except Exception as exc:
            logger.warning(f"Falha ao listar objetos FAISS no S3: {exc}")
        return objects

    def _download_faiss_index_from_s3(self, corpus_fingerprint: str) -> bool:
        if not self._is_s3_persistence_enabled():
            return False

        bucket, prefix = self._s3_index_location(corpus_fingerprint)
        if not bucket or not prefix:
            return False

        objects = self._list_s3_index_objects(bucket, prefix)
        if not objects:
            return False

        index_dir = self._faiss_index_dir(corpus_fingerprint)
        if index_dir.exists():
            shutil.rmtree(index_dir)

        for obj in objects:
            key = obj.get("Key", "")
            if not key or key.endswith("/"):
                continue

            relative_key = key[len(prefix) :]
            if not relative_key:
                continue

            target_path = index_dir / relative_key
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("wb") as f:
                self._get_s3_client().download_fileobj(bucket, key, f)

        logger.info(f"☁️ Índice FAISS baixado do S3 para {index_dir}")
        return True

    def _upload_faiss_index_to_s3(self, index_dir: Path, corpus_fingerprint: str) -> bool:
        if not self._is_s3_persistence_enabled() or not index_dir.exists():
            return False

        bucket, prefix = self._s3_index_location(corpus_fingerprint)
        if not bucket or not prefix:
            return False

        for root, _, files in os.walk(index_dir):
            for name in files:
                local_file = Path(root) / name
                relative_path = local_file.relative_to(index_dir).as_posix()
                key = f"{prefix}{relative_path}"
                with local_file.open("rb") as f:
                    self._get_s3_client().upload_fileobj(f, bucket, key)

        logger.info(f"☁️ Índice FAISS enviado para S3: {bucket}/{prefix}")
        return True

    def _run_rag(self, question: str, file_paths: List[str], persist_to_s3: bool = True) -> str:
        if not file_paths:
            return "Nenhum arquivo válido foi fornecido para análise."

        logger.info(f"📂 Executando RAG com arquivos: {file_paths}")

        manifest = self._build_corpus_manifest(file_paths)
        index_dir = self._faiss_index_dir(manifest["corpus_fingerprint"])
        vector_store = self._load_faiss_index(index_dir, manifest)
        s3_enabled = persist_to_s3 and self._is_s3_persistence_enabled()

        if vector_store is None and s3_enabled:
            if self._download_faiss_index_from_s3(manifest["corpus_fingerprint"]):
                vector_store = self._load_faiss_index(index_dir, manifest)

        if vector_store is None:
            docs = []
            for fp in file_paths:
                try:
                    if fp.startswith("s3://"):
                        print(f"📥 Verificando cache local do S3: {fp}")
                        fp_local = self._ensure_s3_cached(fp)
                    else:
                        fp_local = fp

                    if not Path(fp_local).exists():
                        logger.warning(f"Arquivo não encontrado: {fp_local}")
                        continue

                    loader = UnstructuredFileLoader(fp_local)
                    docs.extend(loader.load())

                except Exception as e:
                    logger.error(f"Erro ao carregar {fp}: {e}")

            if not docs:
                return "Nenhum conteúdo pôde ser carregado a partir dos arquivos."

            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
            all_splits = text_splitter.split_documents(docs)
            vector_store = FAISS.from_documents(all_splits, self.embeddings)
            try:
                self._save_faiss_index(index_dir, vector_store, manifest)
                if s3_enabled:
                    self._upload_faiss_index_to_s3(index_dir, manifest["corpus_fingerprint"])
            except Exception as e:
                logger.warning(f"Falha ao persistir FAISS: {e}")

        prompt = ChatPromptTemplate.from_template("""
        Você é um especialista em RAG (Retrieval-Augmented Generation).
        Responda a PERGUNTA SOMENTE com base no DOCUMENTO abaixo.

        --- DOCUMENTO:
        {context}

        --- PERGUNTA:
        {question}
                                                  
        IMPORTANTE: NUNCA INVENTE INFORMAÇÕES, SE BASEIE UNICAMENTE NO CONTEXTO DOCUMENTO.                    
                                                
        """)

        class State(TypedDict):
            question: str
            context: List[Document]
            answer: str

        def retrieve(state: State):
            retrieved_docs = vector_store.similarity_search(state["question"], k=100)
            return {"context": retrieved_docs}

        def generate(state: State):
            docs_content = "\n\n".join(doc.page_content for doc in state["context"])
            messages = prompt.format_messages(question=state["question"], context=docs_content)
            response = self.llm.invoke(messages)
            answer_msg = response.content
            return {"answer": answer_msg}

        graph_builder = StateGraph(State).add_sequence([retrieve, generate])
        graph_builder.add_edge(START, "retrieve")
        graph = graph_builder.compile()

        result = graph.invoke({"question": question})
        answer = result.get("answer", "").strip()
        return answer or "Não encontrei essa informação no documento."

    def _execute_with_retry(
        self,
        func,
        /,
        *args,
        retries: int = 4,
        initial_delay: float = 0.5,
        backoff: float = 2.0,
        **kwargs,
    ):
        attempt = 0
        delay = initial_delay
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                attempt += 1
                if attempt >= retries:
                    logger.warning(f"{_callable_name(func)} falhou após {attempt} tentativas: {exc}")
                    raise
                logger.warning(
                    f"{_callable_name(func)} tentativa {attempt}/{retries} falhou: {exc}. Repetindo em {delay:.1f}s."
                )
                time.sleep(delay)
                delay *= backoff

    # Tool fixa
    def make_tool(self, path_list: List[str]):
        def _tool(query: str):
            try:
                response = self._execute_with_retry(
                    self._run_rag,
                    question=query,
                    file_paths=path_list,
                )
                return {"content": response, "role": "assistant", "name": "rag_agent", "terminate": True}
            except Exception as e:
                return {"content": f"Erro ao executar RAG: {e}", "role": "assistant", "name": "rag_agent", "terminate": True}
        return _tool

    # Tool dinâmica
    def make_tool_from_uploaded(self):
        def _tool(query: str, files: List[dict] | None = None):
            try:
                requested_files = []
                if isinstance(files, list):
                    requested_files = [
                        f.get("filepath") for f in files
                        if isinstance(f, dict) and f.get("filepath")
                    ]

                valid_requested = [
                    fp for fp in requested_files
                    if fp and Path(fp).exists()
                ]

                if requested_files and not valid_requested:
                    return {"content": "Nenhum caminho de arquivo válido foi encontrado no upload mais recente.", "role": "assistant", "name": "rag_agent", "terminate": True}

                if valid_requested:
                    self._last_uploaded_file_paths = valid_requested
                    file_paths_to_use = valid_requested
                else:
                    cached_paths = [
                        fp for fp in self._last_uploaded_file_paths
                        if Path(fp).exists()
                    ]
                    if not cached_paths:
                        return {"content": "Nenhum arquivo foi recebido.", "role": "assistant", "name": "rag_agent", "terminate": True}

                    file_paths_to_use = cached_paths
                    logger.info("♻️ Reusando arquivo enviado anteriormente para consulta RAG.")

                response = self._execute_with_retry(
                    self._run_rag,
                    question=query,
                    file_paths=file_paths_to_use,
                    persist_to_s3=False,
                )
                return {"content": response, "role": "assistant", "name": "rag_agent", "terminate": True}

            except Exception as e:
                return {"content": f"Erro ao processar RAG dinâmico: {e}", "role": "assistant", "name": "rag_agent", "terminate": True}

        return _tool


# ==========================================================
# TESTE LOCAL
# ==========================================================
if __name__ == "__main__":
    rag_toolkit = RAGToolKit()

    documentos_locais = [
        "s3://agent-core/multimedia/cmh5d527x0005w76v1rximdzn/910f042a-30d6-4800-be42-fb5d66ebb4d7.pdf",
    ]

    rag_tool_fixo = rag_toolkit.make_tool(documentos_locais)

    pergunta = "Me informe em detalhes onde está escrito no código de ética da NeoEnergia que nãodevemos aceitar este presente"
    #pergunta = "A Neoenergia é uma empresa líder na fabricação de Aguinha Perditti?"
    resposta = rag_tool_fixo(pergunta)

    print("📄 Pergunta:", pergunta)
    print("💬 Resposta:", resposta["content"])
