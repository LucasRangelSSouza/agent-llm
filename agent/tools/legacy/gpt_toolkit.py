import json
import logging
from typing import Any, Dict, List, Optional

from autogen import UserProxyAgent

from agent.infrastructure.runtime.ai_service import normalize_provider
from agent.modules.agents.base_agent_gemini import BaseAgentGeminiVision

logger = logging.getLogger(__name__)


class GPTVisionToolkit:
    """
    Toolkit multimodal que usa o ai_service ativo do template.
    Mantém o nome legado para compatibilidade com os templates já existentes.
    """

    def __init__(self, ai_service=None):
        self.ai_service = ai_service
        self.image_agent = BaseAgentGeminiVision(
            name="runtime_vision_agent",
            system_message="Você é um assistente de visão especializado em descrever e interpretar imagens.",
            ai_service=ai_service,
        ).get()
        self.user_proxy_gpt = UserProxyAgent(
            "user_proxy_gpt",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=0,
        )

    def _parse_uploaded_files(self, uploaded_files):
        if uploaded_files is None:
            return []
        if isinstance(uploaded_files, str):
            try:
                parsed = json.loads(uploaded_files)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return uploaded_files

    def _vision_logic(self, message: str, uploaded_files):
        if normalize_provider((self.ai_service or {}).get("provider")) == "local_gguf":
            return "O provider local gratuito atual não oferece suporte confiável a análise de imagens."

        uploaded_files = self._parse_uploaded_files(uploaded_files)
        image_files = [f for f in uploaded_files if f.get("type", "").startswith("image")]
        if not image_files:
            return "❌ Nenhuma imagem válida foi enviada para análise."

        try:
            media_block = "\n".join([f"<img {f.get('filepath')}>" for f in image_files])
            full_prompt = f"{message}\n\n{media_block}"
            response = self.user_proxy_gpt.initiate_chat(
                self.image_agent,
                message=full_prompt,
            )

            if hasattr(response, "chat_history") and response.chat_history:
                last_message = response.chat_history[-1]
                content = last_message["content"] if isinstance(last_message, dict) and "content" in last_message else str(last_message)
            else:
                content = str(response)

            return {
                "content": content.strip(),
                "role": "assistant",
                "name": "vision_agent",
                "terminate": True,
            }
        except Exception as e:
            logger.exception("Erro durante execução do toolkit multimodal:")
            return {
                "content": f"Erro ao processar imagens com o provider configurado: {str(e)}",
                "role": "assistant",
                "name": "vision_agent",
                "terminate": True,
            }

    def make_tool(self):
        def gpt_vision(
            message: Optional[str] = None,
            question: Optional[str] = None,
            uploaded_files: Optional[List[Dict[str, Any]]] = None,
        ):
            final_message = message or question or "Descreva o conteúdo fornecido."
            return self._vision_logic(message=final_message, uploaded_files=uploaded_files)

        return gpt_vision
