export const DATASOURCE_TYPES = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "mariadb", label: "MariaDB" },
  { value: "sqlserver", label: "SQL Server" },
  { value: "sqlite", label: "SQLite" },
  { value: "athena", label: "Athena" },
  { value: "bigquery", label: "BigQuery" },
];

export const AI_SERVICE_PROVIDERS = [
  {
    value: "openai",
    label: "OpenAI",
    requiresApiKey: true,
    models: ["gpt-5.2", "gpt-5.1", "gpt-4o-mini"],
  },
  {
    value: "claude",
    label: "Claude",
    requiresApiKey: true,
    models: ["claude-sonnet-4", "claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"],
  },
  {
    value: "gemini",
    label: "Gemini",
    requiresApiKey: true,
    models: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
  },
  {
    value: "grok",
    label: "Grok",
    requiresApiKey: true,
    models: ["grok-3-mini", "grok-3-fast", "grok-2-latest"],
  },
  {
    value: "deepseek",
    label: "DeepSeek",
    requiresApiKey: true,
    models: ["deepseek-chat", "deepseek-reasoner", "deepseek-v3"],
  },
  {
    value: "local_gguf",
    label: "Local GGUF",
    requiresApiKey: false,
    models: ["Qwen2.5-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-GGUF", "Gemma-2-2B-It-GGUF"],
  },
];

export const STORAGE_KEYS = {
  token: "agent_ui_token",
  preferences: "agent_ui_preferences",
};

const savedPreferences = (() => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.preferences) || "{}");
  } catch {
    return {};
  }
})();

export const state = {
  token: localStorage.getItem(STORAGE_KEYS.token) || "",
  user: null,
  view: "chat",
  loading: false,
  error: "",
  chats: [],
  activeChatId: null,
  messages: [],
  tenants: [],
  users: [],
  userProfiles: [],
  datasources: [],
  files: [],
  secrets: [],
  aiServices: [],
  templates: [],
  templateDetail: null,
  templateDraft: null,
  templateVersionId: null,
  toolkitCatalog: { agent_types: [], toolkits: [], tools: [] },
  aiServiceCatalog: { providers: AI_SERVICE_PROVIDERS },
  filters: {
    tenantsIncludeInactive: false,
    usersIncludeInactive: false,
    userProfilesIncludeInactive: false,
    datasourcesIncludeInactive: false,
    filesIncludeInactive: false,
    secretsIncludeInactive: false,
    aiServicesIncludeInactive: false,
    templatesIncludeInactive: false,
  },
  modal: null,
  toast: null,
  preferences: {
    theme: savedPreferences.theme || "light",
  },
};

export function persistToken(token) {
  state.token = token || "";
  if (token) {
    localStorage.setItem(STORAGE_KEYS.token, token);
  } else {
    localStorage.removeItem(STORAGE_KEYS.token);
  }
}

export function persistPreferences() {
  localStorage.setItem(STORAGE_KEYS.preferences, JSON.stringify(state.preferences));
}

export function defaultDatasourcePayload() {
  return {
    id: null,
    datasource_id: null,
    name: "",
    kind: "postgresql",
    description: "",
    tenant_id: state.user?.tenant_id || "",
    is_active: true,
    host: "",
    port: 5432,
    database_name: "",
    schema_name: "",
    username: "",
    password: "",
    ssl_mode: "",
    catalog_name: "AwsDataCatalog",
    region_name: "us-east-1",
    output_location: "",
    workgroup: "",
    aws_access_key_id: "",
    aws_secret_access_key: "",
    aws_session_token: "",
    project_id: "",
    dataset_name: "",
    location: "",
    gcs_temp_bucket: "",
    service_account_json: "",
    sqlite_mode: "url",
    sqlite_path: "",
    sqlite_url: "",
    has_password: false,
    has_aws_secret_access_key: false,
    has_aws_session_token: false,
    has_service_account_json: false,
  };
}

export function defaultTemplateAgent(index = 0) {
  return {
    name: `novo_agente_${index + 1}_agent`,
    agent_type: "AssistantAgent",
    prompt: "",
    tools: [],
    allowed_interactions: [],
    file_ids: [],
    secret_ids: [],
    sort_order: index,
    isCollapsed: false,
  };
}

export function defaultTemplateDraft() {
  return {
    id: null,
    template_id: null,
    tenant_id: state.user?.tenant_id || "",
    version_number: null,
    based_on_version_id: null,
    name: "",
    module_name: "",
    description: "",
    general_prompt: "",
    ai_service_id: null,
    datasource_ids: [],
    agents: [defaultTemplateAgent(0)],
  };
}

export function defaultAIServicePayload() {
  return {
    id: null,
    ai_service_id: null,
    tenant_id: state.user?.tenant_id || "",
    provider: "openai",
    name: "",
    description: "",
    model_name: "gpt-5.2",
    api_key: "",
    endpoint_url: "",
    organization_id: "",
    is_active: true,
    has_api_key: false,
  };
}

export function canManageAdminAreas() {
  return state.user?.role === "master" || [
    "templates",
    "ai_services",
    "datasources",
    "files",
    "secrets",
    "users",
    "preferences",
    "user_profiles",
  ].some((resource) => hasPermission(resource, "view"));
}

export function canManageTenants() {
  return state.user?.role === "master";
}

export function hasPermission(resource, action = "view") {
  if (state.user?.role === "master") return true;
  return Boolean(state.user?.permissions?.[resource]?.[action]);
}
