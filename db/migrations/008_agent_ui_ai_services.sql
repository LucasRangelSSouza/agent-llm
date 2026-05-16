CREATE TABLE IF NOT EXISTS agent_ui_ai_services (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    updated_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_ai_services_tenant_name
ON agent_ui_ai_services (tenant_id, name);

CREATE INDEX IF NOT EXISTS ix_agent_ui_ai_services_tenant_provider
ON agent_ui_ai_services (tenant_id, provider, is_active);

ALTER TABLE agent_ui_template_versions
ADD COLUMN IF NOT EXISTS ai_service_id TEXT REFERENCES agent_ui_ai_services(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS ix_agent_ui_template_versions_ai_service
ON agent_ui_template_versions (ai_service_id);
