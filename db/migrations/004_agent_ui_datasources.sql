CREATE TABLE IF NOT EXISTS agent_ui_datasources (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_test_status TEXT,
    last_test_message TEXT,
    last_test_at TIMESTAMPTZ,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    updated_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_datasources_tenant_id
    ON agent_ui_datasources (tenant_id);

CREATE INDEX IF NOT EXISTS idx_agent_ui_datasources_kind
    ON agent_ui_datasources (kind);
