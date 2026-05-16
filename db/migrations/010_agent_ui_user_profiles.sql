CREATE TABLE IF NOT EXISTS agent_ui_user_profiles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES agent_ui_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_ui_user_profiles_tenant_id
    ON agent_ui_user_profiles (tenant_id);

ALTER TABLE agent_ui_users
    ADD COLUMN IF NOT EXISTS profile_id TEXT REFERENCES agent_ui_user_profiles(id) ON DELETE SET NULL;

INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
VALUES (
    'profile_master_global',
    NULL,
    'Master',
    '{
      "templates":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "ai_services":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "datasources":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "users":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "preferences":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "user_profiles":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true}
    }'::jsonb,
    TRUE
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
SELECT
    'profile_admin_' || id,
    id,
    'Admin',
    '{
      "templates":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "ai_services":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "datasources":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "users":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "preferences":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true},
      "user_profiles":{"view":true,"edit":true,"create":true,"view_inactive":true,"deactivate":true}
    }'::jsonb,
    TRUE
FROM agent_ui_tenants
ON CONFLICT (id) DO NOTHING;

INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
SELECT
    'profile_user_' || id,
    id,
    'Usuario',
    '{
      "templates":{"view":false,"edit":false,"create":false,"view_inactive":false,"deactivate":false},
      "ai_services":{"view":false,"edit":false,"create":false,"view_inactive":false,"deactivate":false},
      "datasources":{"view":false,"edit":false,"create":false,"view_inactive":false,"deactivate":false},
      "users":{"view":false,"edit":false,"create":false,"view_inactive":false,"deactivate":false},
      "preferences":{"view":true,"edit":true,"create":false,"view_inactive":false,"deactivate":false},
      "user_profiles":{"view":false,"edit":false,"create":false,"view_inactive":false,"deactivate":false}
    }'::jsonb,
    TRUE
FROM agent_ui_tenants
ON CONFLICT (id) DO NOTHING;

UPDATE agent_ui_users
SET profile_id = CASE
    WHEN role = 'master' THEN 'profile_master_global'
    WHEN role = 'admin' THEN 'profile_admin_' || tenant_id
    ELSE 'profile_user_' || tenant_id
END
WHERE profile_id IS NULL;
