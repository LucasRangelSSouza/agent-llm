ALTER TABLE agent_ui_tenants
ADD COLUMN IF NOT EXISTS tenant_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_tenants_tenant_key
ON agent_ui_tenants (tenant_key)
WHERE tenant_key IS NOT NULL AND tenant_key <> '';

CREATE TABLE IF NOT EXISTS agent_ui_templates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    module_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_templates_tenant_module
ON agent_ui_templates (tenant_id, module_name)
WHERE is_deleted = FALSE;

CREATE TABLE IF NOT EXISTS agent_ui_template_versions (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES agent_ui_templates(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    general_prompt TEXT NOT NULL DEFAULT '',
    compiled_json JSONB,
    validation_errors JSONB,
    source_snapshot JSONB,
    based_on_version_id TEXT REFERENCES agent_ui_template_versions(id) ON DELETE SET NULL,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (template_id, version_number)
);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_agents (
    id TEXT PRIMARY KEY,
    template_version_id TEXT NOT NULL REFERENCES agent_ui_template_versions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_agents_name
ON agent_ui_template_version_agents (template_version_id, name);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_agent_tools (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agent_ui_template_version_agents(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_agent_tools
ON agent_ui_template_version_agent_tools (agent_id, tool_name);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_agent_interactions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agent_ui_template_version_agents(id) ON DELETE CASCADE,
    target_agent_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_agent_interactions
ON agent_ui_template_version_agent_interactions (agent_id, target_agent_name);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_datasources (
    id TEXT PRIMARY KEY,
    template_version_id TEXT NOT NULL REFERENCES agent_ui_template_versions(id) ON DELETE CASCADE,
    datasource_id TEXT NOT NULL REFERENCES agent_ui_datasources(id) ON DELETE RESTRICT,
    alias TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_version_datasources
ON agent_ui_template_version_datasources (template_version_id, datasource_id);

CREATE TABLE IF NOT EXISTS agent_ui_template_deployments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    tenant_key TEXT NOT NULL,
    template_id TEXT NOT NULL REFERENCES agent_ui_templates(id) ON DELETE CASCADE,
    template_version_id TEXT NOT NULL REFERENCES agent_ui_template_versions(id) ON DELETE CASCADE,
    compiled_json JSONB NOT NULL,
    redis_key TEXT NOT NULL,
    deployed_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_active_deployment
ON agent_ui_template_deployments (tenant_id)
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS ix_agent_ui_template_deployments_tenant_key
ON agent_ui_template_deployments (tenant_key, is_active);
