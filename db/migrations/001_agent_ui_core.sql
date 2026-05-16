CREATE TABLE IF NOT EXISTS agent_ui_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_ui_tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cnpj TEXT,
    legal_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_ui_users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES agent_ui_tenants(id) ON DELETE RESTRICT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    about TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_users_tenant_id
    ON agent_ui_users (tenant_id);

CREATE TABLE IF NOT EXISTS agent_ui_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES agent_ui_users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_sessions_user_id
    ON agent_ui_sessions (user_id);

CREATE TABLE IF NOT EXISTS agent_ui_chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES agent_ui_users(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES agent_ui_tenants(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_chats_user_id
    ON agent_ui_chats (user_id);

CREATE TABLE IF NOT EXISTS agent_ui_chat_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES agent_ui_chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_chat_messages_chat_id
    ON agent_ui_chat_messages (chat_id, created_at);
