from typing import Optional, Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.utilities import SQLDatabase
from langchain_community.tools import (
    QuerySQLDatabaseTool,
    InfoSQLDatabaseTool,
)

class SQLToolKit:
    """
    Toolkit for SQL database interaction, including dictionary lookups, SQL query execution, and schema retrieval.

    Provides CrewAI tool interfaces for running SQL queries, mapping column meanings using an LLM,
    and obtaining schema information from configured tables.

    Attributes:
        llm_builder (LLMBuilder): Builder for language models.
        db_uri (str): URI for the database connection.
        db_dict (SQLDatabase): SQLDatabase instance for dictionary lookups.
        db_data (SQLDatabase): SQLDatabase instance for data queries and schema.
    """

    def __init__(
        self,
        db_uri,
        **kwargs
    ) -> None:
        self.llm_builder = None
        self.db_uri = db_uri
        self.db_dict = SQLDatabase.from_uri(self.db_uri)
        self.db_data = SQLDatabase.from_uri(self.db_uri)

    def _dictionary_lookup_logic(self, query: str) -> Dict[str, Any]:
        """
        Looks up data dictionary tables for column meanings and uses an LLM to map columns to user queries.

        Args:
            query (str): The user's question or target for column mapping.

        Returns:
            Dict[str, Any]: Dictionary with success status, column mapping, and error message if any.
        """
        query = input.query
        try:
            dicts = self.settings.database.dict_table
            query_tool = QuerySQLDatabaseTool(db=self.db_dict)

            sql = "\nUNION\n".join(
                [
                    f"SELECT columna, significado, '{d}' as origem FROM {d}"
                    for d in dicts
                ]
            )
            result = query_tool.invoke(sql)

            if not result.strip():

                return {
                    "success": False,
                    "mapping": None,
                    "error": "Não foi possível acessar os dicionários ou eles estão vazios.",
                }

            system_prompt = (
                "Você é um assistente que ajuda a mapear colunas de dados com base nos seus significados.\n"
                "Identifique as colunas mais relevantes para a pergunta do usuário, considerando as descrições fornecidas."
            )
            user_prompt = f"""
            Dicionários considerados: {', '.join(dicts)}
            Pergunta do usuário: {query}

            Colunas disponíveis:
            {result}
            """

            response = self.llm_builder.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            return {"success": True, "mapping": response.content, "error": None}

        except Exception as e:
            return {"success": False, "mapping": None, "error": str(e)}

    def dictionary_lookup(self) -> Any:
        """
        Returns a CrewAI tool for dictionary lookup and column mapping.

        Returns:
            Callable: Tool function for performing dictionary lookups.
        """

        def _tool(query: str) -> dict:
            """
            Look up column meanings in data dictionaries.

            This tool queries the configured dictionary tables and uses an LLM
            to match relevant columns to the user's natural language query.

            Args:
                query (str): User's question or column to look up.

            Returns:
                dict: Lookup result with mapping or error.
            """
            return self._dictionary_lookup_logic(query)

        return _tool

    def run_sql_query(self) -> Any:
        """
        Returns a CrewAI tool for executing SQL queries against the main database.

        Returns:
            Callable: Tool function for executing arbitrary SQL queries.
        """

        def _tool(input_text: str) -> str:
            """
            Execute an arbitrary SQL query.

            This tool receives a SQL query as input and returns the results from the database.

            Args:
                input_text (str): SQL query string to execute.

            Returns:
                str: Query result as a string, or error message.
            """
            if not isinstance(input_text, str) or not input_text.strip():
                return "Nenhuma consulta SQL foi fornecida."
            try:
                query_tool = QuerySQLDatabaseTool(db=self.db_data)
                result = query_tool.invoke(input_text)
                if not result:
                    return [(0,)]
                return result
            except Exception as e:
                return f"Erro ao executar a consulta SQL: {str(e)}"

        return _tool

    def _show_table_schemas_logic(self) -> Dict[str, Any]:
        """
        Retrieves schema information for both WIP and completed data tables.

        Returns:
            Dict[str, Any]: Dictionary with schema information and any errors.
        """
        try:
            schema_tool = InfoSQLDatabaseTool(db=self.db_data)
            schema_cacau_show = schema_tool.invoke("cacau_show")
            return {
                "success": True,
                "schema_cacau_show": schema_cacau_show,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "schema_cacau_show": None,
                "error": str(e),
            }

    def show_table_schemas(self) -> Any:
        """
        Returns a CrewAI tool for retrieving table schemas.

        Returns:
            Callable: Tool function to show WIP and completed table schemas.
        """

        def _tool(input_text: Optional[str] = None) -> Dict[str, Any]:
            """
            Show table schemas for main data tables.

            This tool retrieves schema information for the WIP and completed data tables
            and returns their structure.

            Args:
                input_text (str, optional): Not used. Present for compatibility.

            Returns:
                dict: Schemas of WIP and completed tables, or error information.
            """
            return self._show_table_schemas_logic()

        return _tool
