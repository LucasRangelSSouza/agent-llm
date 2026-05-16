import autogen
from langsmith.integrations.otel import configure
from openinference.instrumentation.autogen import AutogenInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
import dotenv
import os

# Load environment variables
dotenv.load_dotenv("/app/.env")

# Configure LangSmith tracing
#configure(project_name="My First App")

# Instrument AutoGen and OpenAI
AutogenInstrumentor().instrument()
OpenAIInstrumentor().instrument()

# Configure your agents
config_list = [
    {
        "model": "gpt-4",
        "api_key": "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",
    }
]

# Create a code reviewer agent
code_reviewer = autogen.AssistantAgent(
    name="code_reviewer",
    llm_config={"config_list": config_list},
    system_message="""You are an expert code reviewer. Your role is to:
1. Review code for bugs, security issues, and best practices
2. Suggest improvements and optimizations
3. Provide constructive feedback

Always be thorough but constructive in your reviews.""",
)

# Create a user proxy agent
user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=8,
    code_execution_config={"work_dir": "workspace"},
    llm_config={"config_list": config_list},
)

# Start the conversation
user_proxy.initiate_chat(
    code_reviewer,
    message="Please review this Python function for potential improvements.",
)