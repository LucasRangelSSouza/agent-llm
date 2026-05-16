ALTER TABLE agent_ui_chats
ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_agent_ui_chats_user_visible
    ON agent_ui_chats (user_id, is_hidden, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_ui_files (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    storage_file_id TEXT REFERENCES agent_files(id) ON DELETE SET NULL,
    original_filename TEXT NOT NULL DEFAULT '',
    file_url TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    updated_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_files_tenant_id
    ON agent_ui_files (tenant_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_ui_secrets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    secret_value TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    updated_by TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_secrets_tenant_id
    ON agent_ui_secrets (tenant_id, is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_agent_files (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agent_ui_template_version_agents(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL REFERENCES agent_ui_files(id) ON DELETE RESTRICT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_agent_files
    ON agent_ui_template_version_agent_files (agent_id, file_id);

CREATE TABLE IF NOT EXISTS agent_ui_template_version_agent_secrets (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agent_ui_template_version_agents(id) ON DELETE CASCADE,
    secret_id TEXT NOT NULL REFERENCES agent_ui_secrets(id) ON DELETE RESTRICT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_ui_template_agent_secrets
    ON agent_ui_template_version_agent_secrets (agent_id, secret_id);
