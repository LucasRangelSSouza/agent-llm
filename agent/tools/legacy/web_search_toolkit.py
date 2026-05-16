import os
import json
import logging
import datetime
from typing import Any, Dict, List, Optional, Set

import requests
from autogen.agentchat import AssistantAgent
import config as settings
from agent.infrastructure.runtime.ai_service import build_autogen_llm_config

logger = logging.getLogger(__name__)


class WebSearchToolkit:
    """
    Toolkit para buscas na web via Serper.dev, com interpretação automática via LLM.
    Estrutura compatível com Autogen / CrewAI.
    """

    def __init__(
        self,
        model: str = None,
        temperature: float = 0.2,
        n_results: int = 5,
        max_tokens: int = 400,
        preferred_domains: Optional[List[str]] = None,
        ai_service: Optional[Dict[str, Any]] = None,
    ):
        self.ai_service = ai_service
        self.model = model
        self.temperature = temperature
        self.n_results = n_results
        self.max_tokens = max_tokens
        self.preferred_domains = preferred_domains or [
            "cpc.org.br",
            "cfc.org.br",
            "ifrs.org",
            "gov.br",
            "planalto.gov.br",
            "cvm.gov.br",
            "ibgc.org.br",
            "stern.nyu.edu",
            "mheducation.com",
            "mckinsey.com",
        ]

        self.base_url = "https://google.serper.dev"
        self.llm_config = build_autogen_llm_config(
            self.ai_service,
            model_override=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            seed=42,
        )
        self.llm_config["timeout"] = 600
        self.llm_config["cache_seed"] = 42

    # -----------------------------------------------------------------
    # 🔗 Extrai links do retorno Serper (search/news)
    # -----------------------------------------------------------------
    def extract_serper_links(self, data: Dict[str, Any]) -> List[str]:
        links: List[str] = []

        # /search
        for r in (data.get("organic") or []):
            if r.get("link"):
                links.append(r["link"])
            for sl in (r.get("sitelinks") or []):
                if isinstance(sl, dict) and sl.get("link"):
                    links.append(sl["link"])

        for r in (data.get("topStories") or []):
            if r.get("link"):
                links.append(r["link"])

        for r in (data.get("peopleAlsoAsk") or []):
            if r.get("link"):
                links.append(r["link"])

        # /news
        for r in (data.get("news") or []):
            if r.get("link"):
                links.append(r["link"])

        # dedup preservando ordem
        seen: Set[str] = set()
        dedup: List[str] = []
        for u in links:
            if u and u not in seen:
                seen.add(u)
                dedup.append(u)

        return dedup

    def _build_preferred_query(self, query: str) -> Optional[str]:
        if not self.preferred_domains:
            return None
        site_filter = " OR ".join([f"site:{d}" for d in self.preferred_domains])
        return f"{query} ({site_filter})"

    # -----------------------------------------------------------------
    # 🌐 Busca bruta no Serper.dev
    # -----------------------------------------------------------------
    def _make_api_request(self, query: str, search_type: str = "search") -> Dict[str, Any]:
        serper_api_key = os.getenv("SERPER_API_KEY")
        if not serper_api_key:
            raise ValueError("A variável de ambiente SERPER_API_KEY não está configurada.")

        endpoint = f"{self.base_url}/{search_type}"
        payload = {"q": query, "num": self.n_results}
        headers = {
            "X-API-KEY": serper_api_key,
            "Content-Type": "application/json",
        }

        logger.info(f"Buscando '{query}' via Serper.dev ({search_type})...")
        response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            raise ValueError("Resposta vazia da API Serper.")

        return data

    # -----------------------------------------------------------------
    # 🧩 Extrai snippets textuais
    # -----------------------------------------------------------------
    def _process_results(self, data: Dict[str, Any], search_type: str) -> List[str]:
        snippets: List[str] = []

        if search_type == "search" and "organic" in data:
            for result in data["organic"][: self.n_results]:
                snippet = result.get("snippet")
                if snippet:
                    snippets.append(snippet.strip())

        elif search_type == "news" and "news" in data:
            for result in data["news"][: self.n_results]:
                snippet = f"{result.get('title', '')} — {result.get('snippet', '')}"
                if snippet.strip():
                    snippets.append(snippet.strip())

        if not snippets:
            snippets.append("Nenhum resultado relevante encontrado.")

        return snippets

    # -----------------------------------------------------------------
    # 🧠 Interpreta resultados com LLM (1 rodada fixa)
    # -----------------------------------------------------------------
    def _interpret_results(self, query: str, snippets: List[str]) -> str:
        try:
            system_message = (
                "Você é um analista web. Resuma e interprete resultados de pesquisa "
                "com base apenas nas informações fornecidas, sem inventar nada."
            )

            content = "\n".join(snippets)
            user_prompt = (
                f"Pergunta: {query}\n\n"
                f"Resultados da busca:\n{content}\n\n"
                "Responda de forma clara, direta e fundamentada (máximo 3 parágrafos)."
            )

            assistant = AssistantAgent(
                name="web_search_analyst",
                system_message=system_message,
                llm_config=self.llm_config,
                human_input_mode="NEVER",
            )

            reply = assistant.generate_reply(
                messages=[{"role": "user", "content": user_prompt}],
                max_turns=1,
            )

            return reply if isinstance(reply, str) else getattr(reply, "content", str(reply))

        except Exception as e:
            logger.error(f"Erro ao interpretar resultados com LLM: {e}")
            return f"Erro ao interpretar resultados com LLM: {e}"

    # -----------------------------------------------------------------
    # 🔍 Lógica completa de busca e interpretação
    # -----------------------------------------------------------------
    def _search_logic(self, query: str, search_type: str = "search", save_file: bool = False) -> str:
        try:
            preferred_query = self._build_preferred_query(query)

            raw = None
            snippets: List[str] = []
            links: List[str] = []

            # 1) tenta com preferred
            if preferred_query:
                raw = self._make_api_request(preferred_query, search_type)
                snippets = self._process_results(raw, search_type)
                links = self.extract_serper_links(raw)

                # fallback se não achou snippet
                if snippets == ["Nenhum resultado relevante encontrado."]:
                    raw = self._make_api_request(query, search_type)
                    snippets = self._process_results(raw, search_type)
                    links = self.extract_serper_links(raw)
            else:
                raw = self._make_api_request(query, search_type)
                snippets = self._process_results(raw, search_type)
                links = self.extract_serper_links(raw)

            interpreted = self._interpret_results(query, snippets)

            result = {
                "query": query,
                "search_type": search_type,
                "snippets": snippets,
                "links": links,
                "interpreted": interpreted,
            }

            if save_file:
                filename = f"web_search_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                logger.info(f"Resultados salvos em {filename}")

            # saída final: texto + fontes
            if links:
                interpreted += "\n\nFontes (links):\n" + "\n".join(f"- {u}" for u in links)

            return interpreted

        except Exception as e:
            logger.error(f"Erro na busca web: {e}")
            return f"Erro ao executar busca na web: {str(e)}"

    # -----------------------------------------------------------------
    # 🧰 Cria função tool compatível com CrewAI / Autogen
    # -----------------------------------------------------------------
    def make_tool(self, search_type: str = "search", save_file: bool = False):
        def _tool(query: str) -> str:
            return self._search_logic(query=query, search_type=search_type, save_file=save_file)
        return _tool

# ---------------------------------------------------------------------
# 🧪 Teste manual
# ---------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web_toolkit = WebSearchToolkit()
    search_tool = web_toolkit.make_tool(search_type="news")

    query = "principais notícias do dia"
    print(f"\n📩 Pergunta: {query}")
    result = search_tool(query)
    print("\n📄 Resposta interpretada:")
    print(result)
