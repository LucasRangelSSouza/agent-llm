import json
import os
import logging
from pathlib import Path

from agent.modules.build.agents_builder import AgentsBuilder
from agent.modules.build.tools_register import ToolRegister
from agent.modules.build.groups_builder import GroupsBuilder
import config as settings
from agent.infrastructure.runtime.ai_service import build_autogen_config_entry, resolve_ai_service


class AgentLoader:
    """
    Classe responsável por carregar um módulo do template Agent,
    inicializar agentes, registrar ferramentas e montar o grupo.
    """

    def __init__(
        self,
        module_name: str = "Demo",
        permissions: dict = {},
        session_id='unknown',
        user_id='unknown',
        tenant_id='default',
        agent_template: dict | None = None,
    ):
        self.module_name = module_name

        self.permissions = permissions
        self.user_id = user_id
        self.tenant_id = tenant_id

        # === Caminho do template ===
        BASE_PATH = Path(__file__).resolve().parents[2]
        TEMPLATE_PATH = os.path.join(BASE_PATH, settings.AGENT_CONFIG)
        AUDIT_PATH = os.path.join(BASE_PATH, settings.AUDIT_MODULE_CONFIG)

        if agent_template is not None:
            self.agent_template = agent_template
        elif self.module_name.lower() == 'audit':
            with open(AUDIT_PATH, "r", encoding="utf-8") as f:
                self.agent_template = json.load(f)
        else:
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                self.agent_template = json.load(f)

        # Taxonomia/RAG automatico foi removido do boot do agente.
        # Contexto agora vem do template, das tools explicitamente habilitadas
        # e do historico recente do chat atual.

        # === Configuração do LLM ===
        self.ai_service = resolve_ai_service(self.agent_template, self.module_name)
        self.llm_config = build_autogen_config_entry(self.ai_service)

        # === Controle de sessão e histórico ===
        self.session_id = session_id
        self.session_histories = {}

        self.logger = logging.getLogger(__name__)
        #self.logger.disabled = True


    # ==========================================================
    # 🔹 MÉTODOS AUXILIARES
    # ==========================================================
    def save_history(self, history):
        """Salva o histórico atual da sessão."""
        self.session_histories[self.session_id] = history

    def get_history(self):
        """
        Retorna o histórico apenas dos agentes do módulo especificado no template.
        """
        submodules = self.agent_template.get(self.module_name, {}).get("submodules", {})
        agent_names = list(submodules.keys())

        session_data = self.session_histories.get(self.session_id, {})
        history = {agent: session_data.get(agent, []) for agent in agent_names}
        return history

    # ==========================================================
    # 🔹 MÉTODO PRINCIPAL
    # ==========================================================
    def load(self):
        """
        Carrega e inicializa o módulo do template.
        Retorna: group_chat, group_manager, agents_builder, history
        """
        self.logger.info(f"Carregando módulo '{self.module_name}'...")

        # === 1️⃣ Histórico ===
        history = self.get_history()

        all_messages = []
        history_limit = max(0, int(getattr(settings, "REDIS_HISTORY_MAX_MESSAGES_PER_AGENT", 8)))
        for msgs in history.values():
            if history_limit:
                all_messages += msgs[-history_limit:]
            else:
                all_messages += msgs

        # === 2️⃣ Filtra agentes conforme permissões ===
        if self.permissions.get("audit") == False:
            submodules = self.agent_template.get(self.module_name, {}).get("submodules", {})
            if "system_auditor_agent" in submodules:
                self.logger.info("🔒 Permissão de auditoria desativada — removendo 'system_auditor_agent'")
                del submodules["system_auditor_agent"]

        # === 3️⃣ Construir agentes do módulo ===
        agents_builder = AgentsBuilder(agent_template=self.agent_template)
        agents_builder.build_module(self.module_name)

        # === 4️⃣ Registrar ferramentas ===
        tool_register = ToolRegister(
            agents_builder,
            self.agent_template,
            session_id=self.session_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
        )
        tool_register.register_all_toolkits(module_name=self.module_name)

        # === 5️⃣ Construir grupo ===
        groups_builder = GroupsBuilder(agents_builder, self.agent_template)
        group_chat, group_manager = groups_builder.build_group(
            self.module_name,
            all_messages,
            self.llm_config,
        )

        self.logger.info("Grupo carregado com sucesso.")

        return group_chat, group_manager, agents_builder, history
    

    def sync_agents_with_history_and_initiate(
        self,
        agents_builder,
        group_manager,
        history,
        message=None,
        logger=None,
        job_id=None,
        user_name=None,
    ):
        """
        Sincroniza os agentes com o histórico (_oai_messages)
        e, se disponível, inicia o chat via user_proxy.

        :param agents_builder: instância de AgentsBuilder com active_agents
        :param group_manager: instância já criada de GroupChatManager
        :param history: dicionário com histórico de mensagens por agente
        :param message: mensagem inicial opcional para iniciar o chat
        :param logger: opcional, logger customizado
        """
        logger = logger or logging.getLogger(__name__)
        if settings.SHOW_AGENT_INTERACTION_LOGS:
            logger.info("Sincronizando agentes com histórico...")
        #print(history)
        user_proxy = None

        for module_name, module_agents in agents_builder.active_agents.items():
            if settings.SHOW_AGENT_INTERACTION_LOGS:
                logger.info(f"Módulo: {module_name}")

            for agent_name, agent_obj in module_agents.items():
                # tenta pegar o histórico específico; se não existir, usa lista vazia
                agent_history = history.get(agent_name, [])
                agent_obj._oai_messages = {group_manager: agent_history}

                if settings.SHOW_AGENT_INTERACTION_LOGS:
                    logger.info(f"Agente '{agent_name}' sincronizado ({len(agent_history)} mensagens)")

                # guarda o user_proxy se for encontrado
                if agent_name.lower() in ["user_proxy", "user_proxy_agent", "input_proxy_agent", "output_proxy_agent"]:
                    user_proxy = agent_obj

        # === Se houver user_proxy, inicia o chat ===
        extra_kwargs = {}
        if job_id:
            metadata = {"job_id": job_id}
            if user_name:
                metadata["user_name"] = user_name
            extra_kwargs["langsmith_extra"] = {"metadata": metadata}
        if user_proxy:
            if settings.SHOW_AGENT_INTERACTION_LOGS:
                logger.info("Iniciando chat via user_proxy...")
            if extra_kwargs:
                logger.info(f"LangSmith metadata payload: {extra_kwargs['langsmith_extra']}")
            try:
                user_proxy.initiate_chat(
                    group_manager,
                    message=message or "Olá, vamos começar?",
                    clear_history=False,
                    **extra_kwargs,
                )
                if settings.SHOW_AGENT_INTERACTION_LOGS:
                    logger.info("Chat iniciado com sucesso.")
            except Exception as e:
                from autogen import UserProxyAgent
                error_str = str(e)
                logger.error(f"❌ Erro ao iniciar chat com user_proxy: {error_str}")
                user_proxy = user_proxy = UserProxyAgent(name="user_proxy")

                user_proxy.initiate_chat(
                    group_manager,
                    message=message or "Olá, vamos começar?",
                    clear_history=True,
                    **extra_kwargs,
                )

                # Detecta erro clássico de tool_call quebrado
                if "tool_call" in error_str or "tool_call_ids" in error_str:
                    logger.warning("⚠️ Erro de tool_call detectado — reiniciando chat do zero.")

                    try:
                        # Recria o chat zerado (sem histórico)
                        user_proxy.initiate_chat(
                            group_manager,
                            message=message or "Olá, vamos começar?",
                            clear_history=True,  # força novo contexto
                            **extra_kwargs,
                        )
                        logger.info("✅ Chat reiniciado com sucesso após erro.")
                    except Exception as e2:
                        logger.error(f"❌ Falha ao reiniciar chat limpo: {e2}")
        else:
            logger.warning("⚠️ Nenhum agente 'user_proxy' encontrado nos módulos carregados.")
