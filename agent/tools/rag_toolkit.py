import json
import logging
from typing import Any, Callable, List, Optional

from agent.tools.artifact_store import artifact_summary_text, save_document_artifact
from agent.tools.document_processing_toolkit import DocumentProcessingToolkit


logger = logging.getLogger(__name__)


class RAGToolkit(DocumentProcessingToolkit):
    """
    RAG direcionado aos arquivos vinculados ao agente no template.

    A LLM informa o nome do arquivo logico ou nome original e a tool resolve
    dentro de linked_files do agente atual.
    """

    def __init__(self, linked_files: Optional[List[dict]] = None, agent_name: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.linked_files = list(linked_files or [])
        self.agent_name = agent_name

    def query_agent_rag(self) -> Callable[..., str]:
        def _tool(
            query: str,
            file_name: Optional[str] = None,
            file_names: Optional[Any] = None,
            max_chunks: int = 12,
        ) -> str:
            try:
                selected_files = self._resolve_linked_files(file_name=file_name, file_names=file_names)
                if not selected_files:
                    return self._json(
                        {
                            "success": False,
                            "error": "Nenhum arquivo vinculado ao agente corresponde ao nome informado.",
                            "available_files": [item.get("name") or item.get("original_filename") or item.get("id") for item in self.linked_files],
                        }
                    )

                paths = [item.get("url") for item in selected_files if item.get("url")]
                if not paths:
                    return self._json({"success": False, "error": "Os arquivos vinculados nao possuem URL utilizavel."})

                resolved_paths = self._resolve_file_paths(file_paths=paths)
                docs = self._extract_documents(resolved_paths)
                chunks = self._split_documents(docs)
                answer = self._run_rag(query=query, file_paths=resolved_paths, max_chunks=max_chunks, chunks=chunks)
                artifact = save_document_artifact(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    chat_id=self.session_id,
                    module_name=self.module_name,
                    agent_name=self.agent_name,
                    label=f"{self.agent_name or 'rag'}_document",
                    content={
                        "document_summary": answer,
                        "answer": answer,
                        "query": query,
                        "files": [
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "original_filename": item.get("original_filename"),
                                "url": item.get("url"),
                            }
                            for item in selected_files
                        ],
                        "chunks": [{"text": doc.page_content, "metadata": doc.metadata} for doc in chunks],
                    },
                    source_tool="rag_toolkit.query_agent_rag",
                    source_type="linked_rag",
                    metadata={"max_chunks": max_chunks},
                )
                return self._json(
                    {
                        "success": True,
                        "agent_name": self.agent_name,
                        "matched_files": [
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "original_filename": item.get("original_filename"),
                                "url": item.get("url"),
                            }
                            for item in selected_files
                        ],
                        "answer": answer,
                        "artifact": artifact,
                        "artifact_summary": artifact_summary_text(artifact),
                    }
                )
            except Exception as exc:
                logger.exception("Erro ao executar RAG do agente.")
                return self._json({"success": False, "error": str(exc)})

        return _tool

    def _resolve_linked_files(self, file_name: Optional[str], file_names: Optional[Any]) -> List[dict]:
        requested = []
        if file_name:
            requested.append(str(file_name))
        if file_names is not None:
            if isinstance(file_names, str):
                text = file_names.strip()
                if text.startswith("["):
                    try:
                        requested.extend(json.loads(text))
                    except Exception:
                        requested.append(text)
                else:
                    requested.append(text)
            elif isinstance(file_names, list):
                requested.extend(file_names)

        if not requested:
            return list(self.linked_files)

        matches = []
        seen_ids = set()
        for target in requested:
            normalized_target = str(target or "").strip().lower()
            if not normalized_target:
                continue
            for item in self.linked_files:
                candidates = [
                    str(item.get("name") or "").strip().lower(),
                    str(item.get("original_filename") or "").strip().lower(),
                    str(item.get("id") or "").strip().lower(),
                ]
                if normalized_target in candidates or any(normalized_target in candidate for candidate in candidates if candidate):
                    if item.get("id") in seen_ids:
                        continue
                    seen_ids.add(item.get("id"))
                    matches.append(item)
                    break
        return matches
