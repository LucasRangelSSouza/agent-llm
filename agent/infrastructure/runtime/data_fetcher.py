import config as settings
import psycopg2
from psycopg2.extras import RealDictCursor


def _connect_front_db():
    return psycopg2.connect(
        host=settings.RDS_FRONT_HOST,
        port=settings.RDS_FRONT_PORT,
        database=settings.RDS_FRONT_DB,
        user=settings.RDS_FRONT_USER,
        password=settings.RDS_FRONT_PASSWORD,
        cursor_factory=RealDictCursor,
    )


def get_user_name(user_id: str):
    if not user_id or user_id == "unknown":
        return "unknown"

    conn = None
    try:
        conn = _connect_front_db()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT full_name
                FROM agent_ui_users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            result = cursor.fetchone()
        return result["full_name"] if result and result.get("full_name") else "unknown"
    except Exception as error:
        print(f"Erro ao buscar usuario: {error}")
        return "unknown"
    finally:
        if conn:
            conn.close()


def get_permissions(user_id: str) -> dict:
    default_permissions = {
        "audit": False,
        "audit.read": False,
    }

    if not user_id or user_id == "unknown":
        return default_permissions

    conn = None
    try:
        conn = _connect_front_db()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT role
                FROM agent_ui_users
                WHERE id = %s
                  AND is_active = TRUE
                LIMIT 1
                """,
                (user_id,),
            )
            result = cursor.fetchone()

        if not result:
            return default_permissions

        role = str(result.get("role") or "").strip().lower()
        audit_allowed = role in {"master", "admin"}
        return {
            "audit": audit_allowed,
            "audit.read": audit_allowed,
        }
    except Exception as error:
        print(f"Erro ao buscar permissoes do usuario {user_id}: {error}")
        return default_permissions
    finally:
        if conn:
            conn.close()
