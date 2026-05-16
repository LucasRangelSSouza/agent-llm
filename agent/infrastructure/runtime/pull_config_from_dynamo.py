import boto3
import json
from botocore.exceptions import ClientError
from collections import defaultdict
import config as settings

def rebuild_agent_structure(items):
    """
    Reconstrói o dicionário hierárquico a partir dos itens da tabela.
    É tolerante: se __module_info__ estiver dentro de submodules, ele é movido
    para o nível de módulo (descricao_mestre, DB_connections).
    """
    data = defaultdict(lambda: {"submodules": {}, "DB_connections": {}, "descricao_mestre": ""})

    for item in items:
        module = item.get("module")
        submodule = item.get("submodule")

        if isinstance(module, dict) and "S" in module:
            module = module["S"]
        if isinstance(submodule, dict) and "S" in submodule:
            submodule = submodule["S"]

        clean_item = {k: v for k, v in item.items() if k not in ("module", "submodule")}
        data[module]["submodules"][submodule] = clean_item

    for module_name, module_obj in list(data.items()):
        subs = module_obj.get("submodules", {})
        module_info = subs.pop("__module_info__", None)

        if module_info:
            if "descricao_mestre" in module_info:
                module_obj["descricao_mestre"] = module_info["descricao_mestre"]
            if "DB_connections" in module_info:
                module_obj["DB_connections"] = module_info["DB_connections"]

        if "DB_connections" in subs and not module_obj["DB_connections"]:
            guessed = subs.pop("DB_connections")
            if isinstance(guessed, dict):
                module_obj["DB_connections"] = guessed

        if "descricao_mestre" in subs and not module_obj["descricao_mestre"]:
            guessed_desc = subs.pop("descricao_mestre")
            if isinstance(guessed_desc, str):
                module_obj["descricao_mestre"] = guessed_desc

        module_obj["submodules"] = subs

    return {k: v for k, v in data.items()}


def get_existing_tables(region: str):
    """Retorna a lista de tabelas disponíveis no DynamoDB."""
    client = boto3.client(
    "dynamodb",
    region_name=settings.AWS_DEFAULT_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
)
    tables = []
    response = client.list_tables()
    tables.extend(response.get("TableNames", []))
    while "LastEvaluatedTableName" in response:
        response = client.list_tables(ExclusiveStartTableName=response["LastEvaluatedTableName"])
        tables.extend(response.get("TableNames", []))
    return tables


def download_dynamo_to_json(table_name: str, json_file: str, region: str = "us-east-1"):
    """Baixa todos os itens da tabela DynamoDB e salva em JSON hierárquico.
       Se a tabela não existir, faz fallback para 'agent_template'."""
    dynamodb = boto3.resource("dynamodb", region_name=region)
    tables = get_existing_tables(region)

    if table_name not in tables:
        print(f"⚠️  Tabela '{table_name}' não encontrada na região '{region}'.")
        if "agent_template" in tables:
            print("🔁 Usando fallback: 'agent_template'.")
            table_name = "agent_template"
        else:
            print("❌ Nenhuma tabela 'agent_template' encontrada. Abortando.")
            return

    table = dynamodb.Table(table_name)

    try:
        print(f"🔄 Lendo dados da tabela '{table_name}'...")
        response = table.scan()
        items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        if not items:
            print(f"⚠️  Nenhum item encontrado na tabela '{table_name}'.")
            return

        structured_data = rebuild_agent_structure(items)

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(structured_data, f, ensure_ascii=False, indent=4)

        print(f"✅ Arquivo salvo com sucesso: {json_file}")
        print(f"📦 Total de módulos exportados: {len(structured_data)}")

    except ClientError as e:
        print(f"❌ Erro ao acessar DynamoDB: {e.response['Error']['Message']}")
    except Exception as e:
        print(f"❌ Erro inesperado: {str(e)}")


# Exemplo de uso direto
if __name__ == "__main__":
    TABLE_NAME = "agent_template"  # <- coloque aqui a tabela desejada
    JSON_FILE = settings.AGENT_CONFIG

    download_dynamo_to_json(TABLE_NAME, JSON_FILE)
