ALTER TABLE agent_ui_sessions
    ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;

UPDATE agent_ui_sessions
SET last_activity_at = COALESCE(last_activity_at, created_at, NOW())
WHERE last_activity_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_ui_sessions_last_activity_at
    ON agent_ui_sessions (last_activity_at);
