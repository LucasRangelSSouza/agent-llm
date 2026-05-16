from typing import Optional
from autogen import GroupChat, GroupChatManager

import config as settings
from agent.infrastructure.observability.setup_logger import LOGGER, LoggerManager


class LoggingGroupChatManager(GroupChatManager):

    def __init__(self, *args, logger: Optional[LoggerManager] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logger or LOGGER

    def _should_hide_large_history_payload(self, message) -> bool:
        if settings.SHOW_HISTORY_QUERY_PAYLOADS:
            return False

        text = str(message)
        is_history_payload = (
            "[METADATA]" in text
            or "tool_responses" in text
            or "Resultado encontrado:" in text
        )
        return is_history_payload and len(text) > 400

    def receive(self, message, sender, request_reply=None, silent=False):
        if settings.SHOW_AGENT_INTERACTION_LOGS:
            if self._should_hide_large_history_payload(message):
                self.logger.log_info(f"{sender.name}: [payload longo de histórico oculto]")
            else:
                self.logger.log_info(f"{sender.name}: {message}")
        return super().receive(message, sender, request_reply, silent)


class BaseGroupChat:
    def __init__(self, llm_config, max_round=60, max_consecutive_auto_reply=20):
        self.llm_config = llm_config
        self.max_round = max_round
        self.max_consecutive_auto_reply = max_consecutive_auto_reply

    def create_group_chat(self, agents, all_messages, transitions):
        """
        Create a base GroupChat.
        
        :param agents: list of agents (e.g. [user_proxy, orchestrator_agent, sql_agent, generalist_agent])
        :param all_messages: accumulated message history
        :param transitions: dictionary with allowed speaker transitions
        :return: GroupChat object
        """
        return GroupChat(
            agents=agents,
            messages=all_messages,
            max_round=self.max_round,
            allowed_or_disallowed_speaker_transitions=transitions,
            speaker_transitions_type="allowed",
        )

    def create_group_manager(self, group_chat, human_input_mode="NEVER"):
        """
        Create a GroupChatManager linked to a GroupChat.
        
        :param group_chat: GroupChat object created previously
        :param human_input_mode: input mode (default: "NEVER")
        :return: GroupChatManager object
        """
        return LoggingGroupChatManager(
            groupchat=group_chat,
            llm_config={"config_list": [self.llm_config]},
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=self.max_consecutive_auto_reply,
        )
