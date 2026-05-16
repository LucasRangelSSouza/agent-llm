import json
import logging
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx
from autogen import UserProxyAgent

from agent.infrastructure.runtime.ai_service import create_multimodal_agent, normalize_provider
import config as settings
from agent.tools.artifact_store import artifact_summary_text, save_document_artifact


logger = logging.getLogger(__name__)


class ImageProcessingToolkit:
    """Analise de imagens usando o ai_service multimodal ativo no template."""

    def __init__(self, ai_service: Optional[dict] = None, **_: Any) -> None:
        self.ai_service = ai_service or {}
        self.tenant_id = _.get("tenant_id")
        self.session_id = _.get("session_id")
        self.user_id = _.get("user_id")
        self.module_name = _.get("module_name")
        self.agent_name = _.get("agent_name")
        self.provider = normalize_provider(self.ai_service.get("provider"))
        self.image_agent = None
        self.user_proxy = None
        self.cache_root = Path(getattr(settings, "RAG_UPLOADS_DIR", settings.UPLOADS_DIR)) / "image_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        if self.provider != "local_gguf":
            self.image_agent = create_multimodal_agent(
                name="runtime_image_processing_agent",
                system_message="Voce e um assistente de visao. Analise imagens com precisao e responda em portugues.",
                ai_service=self.ai_service,
            )
            self.user_proxy = UserProxyAgent(
                "runtime_image_processing_user_proxy",
                human_input_mode="NEVER",
                max_consecutive_auto_reply=0,
            )

    def analyze_image(self):
        def _tool(
            question: Optional[str] = None,
            message: Optional[str] = None,
            files: Optional[Any] = None,
            uploaded_files: Optional[Any] = None,
            uploaded_images: Optional[Any] = None,
        ) -> str:
            try:
                if self.provider == "local_gguf":
                    return self._json(
                        {
                            "success": False,
                            "error": "O provider local gratuito atual nao suporta analise de imagens.",
                        }
                    )

                paths = self._resolve_image_paths(uploaded_images or uploaded_files or files)
                if not paths:
                    return self._json({"success": False, "error": "Nenhuma imagem valida foi recebida."})

                prompt = message or question or "Descreva e interprete a imagem enviada."
                media = "\n".join(f"<img {path}>" for path in paths)
                response = self.user_proxy.initiate_chat(
                    self.image_agent,
                    message=f"{prompt}\n\n{media}",
                )
                content = self._extract_response_text(response)
                artifact = self._build_artifact(paths=paths, prompt=prompt, answer=content)
                return self._json(
                    {
                        "success": True,
                        "answer": content,
                        "images": [Path(path).name for path in paths],
                        "artifact": artifact,
                        "artifact_summary": artifact.get("artifact_summary"),
                    }
                )
            except Exception as exc:
                logger.exception("Erro ao processar imagem.")
                return self._json({"success": False, "error": str(exc)})

        return _tool

    def _resolve_image_paths(self, value: Any) -> List[str]:
        paths = []
        for path in self._extract_paths(value):
            clean_path = str(path or "").strip()
            local_path = self._ensure_local_image(clean_path)
            if local_path and Path(local_path).exists():
                paths.append(local_path)
        return paths

    def _ensure_local_image(self, path: str) -> Optional[str]:
        if path.startswith("http://") or path.startswith("https://"):
            digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
            suffix = Path(path.split("?", 1)[0]).suffix or ".bin"
            local_path = self.cache_root / f"{digest}{suffix}"
            if not local_path.exists():
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    response = client.get(path)
                    response.raise_for_status()
                    local_path.write_bytes(response.content)
            return str(local_path)
        return path

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
            if "uploaded_images" in value:
                return self._extract_paths(value.get("uploaded_images"))
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

    def _extract_response_text(self, response: Any) -> str:
        history = getattr(response, "chat_history", None)
        if history:
            last = history[-1]
            if isinstance(last, dict):
                return str(last.get("content") or "").strip()
            return str(last).strip()
        return str(response).strip()

    def _json(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _build_artifact(self, *, paths: List[str], prompt: str, answer: str) -> dict:
        artifact = save_document_artifact(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            chat_id=self.session_id,
            module_name=self.module_name,
            agent_name=self.agent_name,
            label=f"{self.agent_name or 'image'}_document",
            content={
                "document_summary": answer,
                "answer": answer,
                "prompt": prompt,
                "files": [Path(path).name for path in paths],
                "image_paths": paths,
                "chunks": [{"text": answer, "metadata": {"type": "image_analysis"}}],
            },
            source_tool="image_processing_toolkit.analyze_image",
            source_type="image_analysis",
            metadata={"provider": self.provider},
        )
        artifact["artifact_summary"] = artifact_summary_text(artifact)
        return artifact
