import json
from pathlib import Path

from autogen import AssistantAgent, UserProxyAgent

import config as settings
from agent.infrastructure.runtime.ai_service import build_autogen_llm_config, resolve_ai_service


class MasterOrchestratorAgent(AssistantAgent):
    """
    Agente orquestrador responsável por escolher EXATAMENTE UM módulo
    com base na mensagem do usuário e nas descrições disponíveis.
    """

    def __init__(self, model=None, seed=42, modules=None, agent_template=None):
        ai_service = resolve_ai_service(agent_template)
        llm_config = build_autogen_llm_config(
            ai_service,
            model_override=model,
            seed=seed,
        )

        self.modules = modules or []

        super().__init__(
            name="master_orchestrator",
            system_message=(
                "Você é um orquestrador que escolhe EXATAMENTE UM módulo "
                "com base na mensagem do usuário e nas descrições disponíveis.\n\n"
                "Regras:\n"
                "1. Responda APENAS com o nome do módulo.\n"
                "2. Nunca diga 'não sei' ou 'nenhum'.\n"
                "3. Sempre escolha o mais compatível.\n"
                "4. Não explique sua escolha.\n"
                "5. Sempre finalize a conversa após responder."
                "Só envie pro modulo auditor perguntas do tipo:"
                "- Qual a ultima interacao do funcionario X?"
                "- Quais as ultimas solicitacoes do agente A?"
                "- Quem utilizou o modulo XX por ultimo?"
                "- Qual o agente mais utuilziado no sistema?"
            ),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )

        self.user_proxy = UserProxyAgent(
            name="user_proxy",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=1,
        )

    def load_combined_templates(self):
        base_dir = Path(__file__).resolve().parents[3]
        main_template_path = base_dir / settings.AGENT_CONFIG
        audit_template_path = base_dir / settings.AUDIT_MODULE_CONFIG

        combined = {}

        if main_template_path.exists():
            with open(main_template_path, "r", encoding="utf-8") as f:
                try:
                    combined.update(json.load(f))
                except json.JSONDecodeError:
                    pass

        if audit_template_path.exists():
            with open(audit_template_path, "r", encoding="utf-8") as f:
                try:
                    audit_data = json.load(f)
                    for k, v in audit_data.items():
                        if k not in combined:
                            combined[k] = v
                except json.JSONDecodeError:
                    pass

        return combined

    def select_module(self, message: str, template: dict, allowed_modules: list[str]) -> str:
        if self.modules:
            considered_modules = [m for m in self.modules if m.lower() in [t.lower() for t in template.keys()]]
            if not considered_modules:
                considered_modules = list(template.keys())
        else:
            considered_modules = list(template.keys())

        if not considered_modules:
            return "Demo"

        descriptions = []
        for mod_name in considered_modules:
            mod_data = template.get(mod_name) or next(
                (template[k] for k in template.keys() if k.lower() == mod_name.lower()),
                {},
            )
            desc = mod_data.get("descricao_mestre") or mod_data.get("description") or ""
            descriptions.append(f"- {mod_name}: {desc if desc else '(sem descrição)'}")

        user_prompt = (
            f"Mensagem do usuário: {message}\n\n"
            f"Módulos disponíveis:\n{chr(10).join(descriptions)}\n\n"
            f"Escolha SOMENTE o nome exato de um módulo entre: {', '.join(considered_modules)}."
        )

        try:
            response = self.generate_reply(messages=[{"role": "user", "content": user_prompt}])
            if not response:
                return "Demo"
            response = response.strip()
        except Exception:
            return "Demo"

        for mod in considered_modules:
            if mod.lower() == response.lower():
                return mod
            if mod.lower() in response.lower():
                return mod

        return considered_modules[0]
