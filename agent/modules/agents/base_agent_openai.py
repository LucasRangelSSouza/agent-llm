from agent.infrastructure.runtime.ai_service import create_assistant_agent


class BaseAgentOpenAi:
    def __init__(self, name: str, system_message: str, ai_service=None):
        self.agent = create_assistant_agent(
            name=name,
            system_message=system_message,
            ai_service=ai_service,
        )

    def get(self):
        return self.agent
