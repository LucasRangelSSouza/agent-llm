import time
import json
from typing import Any, List, Dict

import boto3
from botocore.exceptions import ClientError
from urllib.parse import urlparse



class SQLAthenaToolKit:
    """
    Toolkit para executar queries SQL no Amazon Athena usando boto3.

    Essa classe foi pensada para ser usada como uma "tool" em agentes (CrewAI, etc.),
    expondo um método `run_sql_query()` que retorna uma função (_tool) capaz de
    receber uma query SQL em texto e devolver o resultado.

    Ela NÃO se preocupa com schema das tabelas, pois assume que outra camada do
    agente já conhece/valida o schema.
    """

    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_session_token: str | None,
        region_name: str,
        athena_database: str,
        athena_output_location: str,
        poll_interval: int = 2,
    ) -> None:
        """
        Inicializa o toolkit de Athena.

        Args:
            aws_access_key_id (str): AWS Access Key ID.
            aws_secret_access_key (str): AWS Secret Access Key.
            region_name (str): Região AWS onde o Athena está (ex.: 'us-east-1').
            athena_database (str): Nome do database do Athena a ser usado.
            athena_output_location (str): Caminho S3 para salvar resultados
                (ex.: 's3://meu-bucket-athena-results/').
            poll_interval (int): Intervalo (segundos) entre checagens de status da query.
        """
        self.region_name = region_name
        self.athena_database = athena_database
        self.athena_output_location = athena_output_location
        self.poll_interval = poll_interval

        # Cria client do Athena
        self.client = boto3.client(
            "athena",
            region_name=self.region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )

        # Client S3 para garantir bucket temporário
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )

        # Loga conta, região e bucket temporário
        self._log_aws_context(aws_access_key_id, aws_secret_access_key, aws_session_token)

        # Garante que o bucket temporário exista
        self._ensure_temp_bucket()

    # ============================
    # LÓGICA INTERNA: EXECUTAR QUERY
    # ============================

    def _extract_bucket_name(self) -> str:
        """
        Extrai o nome do bucket a partir do athena_output_location (s3://bucket/prefix/).
        """
        parsed = urlparse(self.athena_output_location)

        if parsed.scheme != "s3":
            raise ValueError(
                f"athena_output_location inválido: {self.athena_output_location}. "
                "Deve ser no formato s3://meu-bucket/pasta/"
            )

        # Em URLs S3, o bucket costuma estar em netloc; fallback para path se necessário
        bucket = parsed.netloc or parsed.path.split("/")[0]
        if not bucket:
            raise ValueError(
                f"Não foi possível extrair o bucket de: {self.athena_output_location}"
            )

        return bucket

    def _log_aws_context(self, aws_access_key_id: str, aws_secret_access_key: str, aws_session_token: str | None) -> None:
        """
        Loga conta AWS, região e bucket temporário.
        """
        try:
            sts_client = boto3.client(
                "sts",
                region_name=self.region_name,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
            )
            identity = sts_client.get_caller_identity()
            account_id = identity.get("Account", "desconhecida")
        except Exception as e:
            account_id = f"erro_ao_obter_conta ({e})"

        bucket_name = self._extract_bucket_name()

        print(
            f"[SQLAthenaToolKit] Rodando na conta AWS: {account_id} | "
            f"Região: {self.region_name} | "
            f"Bucket temporário (Athena output): {bucket_name}"
        )

    def _ensure_temp_bucket(self) -> None:
        """
        Garante que o bucket temporário (onde o Athena grava resultados) exista.
        Se não existir, tenta criar.
        """
        bucket_name = self._extract_bucket_name()

        try:
            # Verifica se o bucket já existe
            self.s3_client.head_bucket(Bucket=bucket_name)
            print(f"[SQLAthenaToolKit] Bucket temporário já existe: {bucket_name}")
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "")

            # Se não existir, tenta criar
            if error_code in ("404", "NoSuchBucket", "NotFound"):
                print(f"[SQLAthenaToolKit] Bucket {bucket_name} não existe. Criando...")

                create_kwargs = {"Bucket": bucket_name}
                if self.region_name != "us-east-1":
                    create_kwargs["CreateBucketConfiguration"] = {
                        "LocationConstraint": self.region_name
                    }

                try:
                    self.s3_client.create_bucket(**create_kwargs)
                    print(f"[SQLAthenaToolKit] Bucket criado com sucesso: {bucket_name}")
                except ClientError as ce:
                    # Se já existir e for seu, ok; se existir de outro dono, vai falhar
                    code = ce.response["Error"].get("Code", "")
                    if code in ("BucketAlreadyOwnedByYou",):
                        print(
                            f"[SQLAthenaToolKit] Bucket {bucket_name} já era seu. Prosseguindo."
                        )
                    else:
                        raise RuntimeError(
                            f"Falha ao criar bucket temporário {bucket_name}: {ce}"
                        ) from ce
            else:
                # Outro erro (permissão, etc.)
                raise RuntimeError(
                    f"Erro ao verificar existência do bucket {bucket_name}: {e}"
                ) from e


    def _execute_athena_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Executa uma query no Athena e retorna os resultados como lista de dicts.

        Cada dict representa uma linha, com chave = nome da coluna.

        Args:
            query (str): Query SQL a ser executada no Athena.

        Returns:
            List[Dict[str, Any]]: Lista de linhas retornadas pela query.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Nenhuma consulta SQL válida foi fornecida.")

        try:
            # 1) Inicia execução da query
            response = self.client.start_query_execution(
                QueryString=query,
                QueryExecutionContext={"Database": self.athena_database},
                ResultConfiguration={"OutputLocation": self.athena_output_location},
            )
            query_execution_id = response["QueryExecutionId"]

            # 2) Polling até a query finalizar
            while True:
                query_status = self.client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                state = query_status["QueryExecution"]["Status"]["State"]

                if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                    if state != "SUCCEEDED":
                        reason = query_status["QueryExecution"]["Status"].get(
                            "StateChangeReason", "Sem motivo detalhado"
                        )
                        raise RuntimeError(
                            f"Query não foi bem-sucedida. Estado: {state}. Motivo: {reason}"
                        )
                    break

                time.sleep(self.poll_interval)

            # 3) Buscar resultados paginados
            results_paginator = self.client.get_paginator("get_query_results")
            results_iter = results_paginator.paginate(QueryExecutionId=query_execution_id)

            rows: List[Dict[str, Any]] = []
            column_info = None

            for page in results_iter:
                if column_info is None:
                    column_info = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]

                for row in page["ResultSet"]["Rows"]:
                    # Ignora linha de header (primeira linha com nomes de colunas)
                    if (
                        "VarCharValue" in row["Data"][0]
                        and row["Data"][0]["VarCharValue"] == column_info[0]["Name"]
                    ):
                        continue

                    row_dict: Dict[str, Any] = {}
                    for col, cell in zip(column_info, row["Data"]):
                        col_name = col["Name"]
                        value = cell.get("VarCharValue", None)
                        row_dict[col_name] = value
                    rows.append(row_dict)

            return rows

        except ClientError as e:
            raise RuntimeError(f"Erro do AWS Client ao executar query no Athena: {e}")
        except Exception as e:
            raise RuntimeError(f"Erro ao executar query no Athena: {e}")

    # ============================
    # TOOL: RUN_SQL_QUERY
    # ============================

    def run_sql_query(self) -> Any:
        """
        Retorna uma função (tool) para executar queries SQL no Athena.

        Essa função é pensada para ser registrada como tool em agentes (CrewAI, etc.).

        Returns:
            Callable: Função que recebe uma string com a query SQL e devolve
                      o resultado em formato de string (JSON) ou mensagem de erro.
        """

        def _tool(input_text: str) -> str:
            """
            Executa uma query SQL no Athena e retorna o resultado.

            Args:
                input_text (str): Query SQL a ser executada.

            Returns:
                str: Resultado em formato JSON (lista de linhas) ou mensagem
                     indicando que não houve registros.
            """
            if not isinstance(input_text, str) or not input_text.strip():
                return "Nenhuma consulta SQL foi fornecida."

            try:
                rows = self._execute_athena_query(input_text)

                if not rows:
                    return "Query executada com sucesso, mas nenhum registro foi retornado."

                # Retorna como JSON bonitinho pra IA conseguir entender bem
                return json.dumps(rows, ensure_ascii=False, indent=2)

            except Exception as e:
                return f"Erro ao executar a consulta SQL no Athena: {str(e)}"

        return _tool
