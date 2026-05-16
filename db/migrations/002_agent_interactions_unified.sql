CREATE TABLE IF NOT EXISTS agent_interactions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    chat_id TEXT,
    session_id TEXT,
    user_id TEXT,
    user_name TEXT,
    interaction_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_question TEXT,
    agent_name TEXT,
    content TEXT,
    module_name TEXT,
    feedback TEXT,
    source TEXT NOT NULL DEFAULT 'ai_runtime',
    legacy_table TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_interactions_runtime
    ON agent_interactions (
        tenant_id,
        session_id,
        interaction_time,
        COALESCE(agent_name, '')
    );

CREATE INDEX IF NOT EXISTS idx_agent_interactions_tenant_time
    ON agent_interactions (tenant_id, interaction_time DESC);

CREATE INDEX IF NOT EXISTS idx_agent_interactions_chat
    ON agent_interactions (chat_id, interaction_time ASC);

CREATE INDEX IF NOT EXISTS idx_agent_interactions_user
    ON agent_interactions (user_id, interaction_time DESC);

CREATE INDEX IF NOT EXISTS idx_agent_interactions_session
    ON agent_interactions (session_id, interaction_time DESC);

DO $$
DECLARE
    rec RECORD;
    sql TEXT;
BEGIN
    FOR rec IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE 'interactions\_%' ESCAPE '\'
    LOOP
        sql := format(
            $fmt$
            INSERT INTO agent_interactions (
                tenant_id,
                chat_id,
                session_id,
                user_id,
                user_name,
                interaction_time,
                user_question,
                agent_name,
                content,
                module_name,
                source,
                legacy_table
            )
            SELECT
                replace(%L, 'interactions_', ''),
                NULLIF(session_id, ''),
                session_id,
                user_id,
                user_name,
                CASE
                    WHEN trim(COALESCE(interaction_time, '')) = '' THEN NOW()
                    ELSE interaction_time::timestamptz
                END,
                user_question,
                agent,
                content,
                module_name,
                'legacy_interactions',
                %L
            FROM %I
            ON CONFLICT DO NOTHING
            $fmt$,
            rec.table_name,
            rec.table_name,
            rec.table_name
        );
        EXECUTE sql;
    END LOOP;

    IF to_regclass('public.decipher_auditor_agent_data') IS NOT NULL THEN
        INSERT INTO agent_interactions (
            tenant_id,
            chat_id,
            session_id,
            user_id,
            user_name,
            interaction_time,
            user_question,
            agent_name,
            content,
            module_name,
            source,
            legacy_table
        )
        SELECT
            'legacy_audit',
            NULLIF(session_id, ''),
            session_id,
            user_id,
            user_name,
            CASE
                WHEN trim(COALESCE(interaction_time, '')) = '' THEN NOW()
                ELSE interaction_time::timestamptz
            END,
            user_question,
            agent,
            content,
            module_name,
            'legacy_audit',
            'decipher_auditor_agent_data'
        FROM decipher_auditor_agent_data
        ON CONFLICT DO NOTHING;
    END IF;
END $$;
