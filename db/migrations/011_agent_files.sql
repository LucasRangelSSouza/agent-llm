CREATE TABLE IF NOT EXISTS agent_files (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES agent_ui_tenants(id) ON DELETE SET NULL,
    user_id TEXT REFERENCES agent_ui_users(id) ON DELETE SET NULL,
    chat_id TEXT REFERENCES agent_ui_chats(id) ON DELETE SET NULL,
    datasource_id TEXT REFERENCES agent_ui_datasources(id) ON DELETE SET NULL,
    template_id TEXT REFERENCES agent_ui_templates(id) ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'upload',
    original_filename TEXT NOT NULL,
    storage_provider TEXT NOT NULL DEFAULT 's3',
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    public_url TEXT,
    content_type TEXT,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    checksum_sha256 TEXT,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_files_tenant_id
    ON agent_files (tenant_id);

CREATE INDEX IF NOT EXISTS idx_agent_files_chat_id
    ON agent_files (chat_id);

CREATE INDEX IF NOT EXISTS idx_agent_files_datasource_id
    ON agent_files (datasource_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_files_bucket_object_key
    ON agent_files (bucket, object_key);
