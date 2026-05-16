from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TenantPayload(BaseModel):
    name: str
    cnpj: Optional[str] = ""
    legal_name: Optional[str] = ""


class UserPayload(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = ""
    about: Optional[str] = ""
    password: str
    role: str = "user"
    tenant_id: Optional[str] = None
    profile_id: Optional[str] = None
    is_active: bool = True


class UserUpdatePayload(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = ""
    about: Optional[str] = ""
    password: Optional[str] = None
    role: str = "user"
    tenant_id: Optional[str] = None
    profile_id: Optional[str] = None
    is_active: bool = True


class UserProfilePayload(BaseModel):
    name: str
    tenant_id: Optional[str] = None
    permissions: dict = {}
    is_active: bool = True


class ChatSendPayload(BaseModel):
    chat_id: Optional[str] = None
    question: str
    modules: Optional[str] = None
    tenant_id: Optional[str] = None


class DatasourcePayload(BaseModel):
    datasource_id: Optional[str] = None
    name: str
    kind: str
    description: Optional[str] = ""
    tenant_id: Optional[str] = None
    is_active: bool = True
    host: Optional[str] = ""
    port: Optional[int] = None
    database_name: Optional[str] = ""
    schema_name: Optional[str] = ""
    username: Optional[str] = ""
    password: Optional[str] = ""
    ssl_mode: Optional[str] = ""
    catalog_name: Optional[str] = ""
    region_name: Optional[str] = ""
    output_location: Optional[str] = ""
    workgroup: Optional[str] = ""
    aws_access_key_id: Optional[str] = ""
    aws_secret_access_key: Optional[str] = ""
    aws_session_token: Optional[str] = ""
    project_id: Optional[str] = ""
    dataset_name: Optional[str] = ""
    location: Optional[str] = ""
    gcs_temp_bucket: Optional[str] = ""
    service_account_json: Optional[str] = ""
    sqlite_mode: Optional[str] = "url"
    sqlite_path: Optional[str] = ""
    sqlite_url: Optional[str] = ""


class AIServicePayload(BaseModel):
    ai_service_id: Optional[str] = None
    tenant_id: Optional[str] = None
    provider: str
    name: str
    description: Optional[str] = ""
    model_name: str
    api_key: Optional[str] = ""
    endpoint_url: Optional[str] = ""
    organization_id: Optional[str] = ""
    is_active: bool = True


class TemplateAgentPayload(BaseModel):
    name: str
    agent_type: str
    prompt: str = ""
    tools: list[str] = []
    allowed_interactions: list[str] = []
    file_ids: list[str] = []
    secret_ids: list[str] = []
    sort_order: int = 0


class TemplateVersionPayload(BaseModel):
    tenant_id: Optional[str] = None
    name: str
    module_name: str
    description: str = ""
    general_prompt: str = ""
    ai_service_id: Optional[str] = None
    datasource_ids: list[str] = []
    agents: list[TemplateAgentPayload] = []
    based_on_version_id: Optional[str] = None


class TemplateDeployPayload(BaseModel):
    template_id: str
    version_id: str


class ActiveStatePayload(BaseModel):
    is_active: bool


class SecretPayload(BaseModel):
    id: Optional[str] = None
    tenant_id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    secret_value: str
    is_active: bool = True
