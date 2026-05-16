import boto3
import json
import time
from botocore.exceptions import ClientError
import config as settings


# -------- CONFIG --------
TABLE_NAME = "agent_template"
REGION = "us-east-1"
JSON_FILE = settings.AGENT_CONFIG
# -------------------------

dynamodb = boto3.client(
    "dynamodb",
    region_name=REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

resource = boto3.resource(
    "dynamodb",
    region_name=settings.AWS_DEFAULT_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)


def recreate_table():
    """Deleta a tabela se existir e recria do zero."""
    try:
        existing_tables = dynamodb.list_tables()["TableNames"]
        if TABLE_NAME in existing_tables:
            print(f"🧨 Tabela '{TABLE_NAME}' já existe. Deletando...")
            dynamodb.delete_table(TableName=TABLE_NAME)

            # Espera deletar completamente
            table = resource.Table(TABLE_NAME)
            print("⏳ Aguardando exclusão completa...")
            table.wait_until_not_exists()
            print("✅ Tabela antiga removida com sucesso.")

        # Cria nova tabela
        print(f"📦 Criando nova tabela '{TABLE_NAME}'...")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "module", "AttributeType": "S"},
                {"AttributeName": "submodule", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "module", "KeyType": "HASH"},
                {"AttributeName": "submodule", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Espera ficar ativa
        table = resource.Table(TABLE_NAME)
        print("⏳ Aguardando tabela ficar ativa...")
        table.wait_until_exists()
        print("✅ Nova tabela criada com sucesso!")

    except ClientError as e:
        print(f"❌ Erro ao recriar tabela: {e}")


def import_json_to_dynamodb():
    """Insere os módulos e submódulos do JSON na tabela."""
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    table = resource.Table(TABLE_NAME)
    count = 0

    for module_name, module_data in data.items():
        # --- 1️⃣ Grava metadados do módulo (nível superior) ---
        descricao_mestre = module_data.get("descricao_mestre", "")
        db_conns = module_data.get("DB_connections", {})

        module_info_item = {
            "module": module_name,
            "submodule": "__module_info__",
            "descricao_mestre": descricao_mestre,
            "DB_connections": db_conns
        }

        table.put_item(Item=module_info_item)
        print(f"✅ Inserido metadado do módulo: {module_name}")
        count += 1

        # --- 2️⃣ Grava submódulos ---
        submodules = module_data.get("submodules", {})
        for sub_name, sub_data in submodules.items():
            item = {
                "module": module_name,
                "submodule": sub_name,
                **sub_data,
            }
            table.put_item(Item=item)
            count += 1
            print(f"✅ Inserido: {module_name} / {sub_name}")

    print(f"🎯 Total de {count} itens importados (módulos + submódulos).")


if __name__ == "__main__":
    recreate_table()
    import_json_to_dynamodb()
