from agent.infrastructure.runtime.ai_service import create_assistant_agent, create_multimodal_agent


class BaseAgentGeminiVision:
    def __init__(self, name: str = "gemini_vision_agent", system_message: str = "", ai_service=None):
        self.agent_vision = create_multimodal_agent(
            name=name,
            system_message=system_message or "You are a helpful multimodal assistant.",
            ai_service=ai_service,
        )

    def get(self):
        return self.agent_vision


class BaseAgentGemini:
    def __init__(self, name: str, system_message: str, ai_service=None):
        self.agent = create_assistant_agent(
            name=name,
            system_message=system_message,
            ai_service=ai_service,
        )

    def get(self):
        return self.agent
