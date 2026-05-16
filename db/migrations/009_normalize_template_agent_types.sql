INSERT INTO agent_ui_schema_migrations (version)
SELECT '009_normalize_template_agent_types.sql'
WHERE NOT EXISTS (
    SELECT 1
    FROM agent_ui_schema_migrations
    WHERE version = '009_normalize_template_agent_types.sql'
);

UPDATE agent_ui_template_version_agents
SET agent_type = CASE
    WHEN agent_type IN ('BaseAgentOpenAi', 'BaseAgentGemini', 'BaseAgentGeminiVision') THEN 'AssistantAgent'
    WHEN agent_type IN ('UserProxyGemini') THEN 'UserProxyAgent'
    ELSE agent_type
END
WHERE agent_type IN ('BaseAgentOpenAi', 'BaseAgentGemini', 'BaseAgentGeminiVision', 'UserProxyGemini');

UPDATE agent_ui_template_versions
SET source_snapshot = jsonb_set(
    source_snapshot,
    '{agents}',
    COALESCE(
        (
            SELECT jsonb_agg(
                CASE
                    WHEN jsonb_typeof(agent_item) = 'object' AND agent_item ? 'agent_type' THEN
                        jsonb_set(
                            agent_item,
                            '{agent_type}',
                            to_jsonb(
                                CASE
                                    WHEN agent_item->>'agent_type' IN ('BaseAgentOpenAi', 'BaseAgentGemini', 'BaseAgentGeminiVision') THEN 'AssistantAgent'
                                    WHEN agent_item->>'agent_type' = 'UserProxyGemini' THEN 'UserProxyAgent'
                                    ELSE agent_item->>'agent_type'
                                END
                            ),
                            false
                        )
                    ELSE agent_item
                END
            )
            FROM jsonb_array_elements(COALESCE(source_snapshot->'agents', '[]'::jsonb)) AS agent_item
        ),
        '[]'::jsonb
    ),
    true
)
WHERE source_snapshot ? 'agents';

UPDATE agent_ui_template_versions
SET compiled_json = (
    SELECT jsonb_object_agg(
        module_key,
        CASE
            WHEN jsonb_typeof(module_value) = 'object' AND module_value ? 'submodules' THEN
                jsonb_set(
                    module_value,
                    '{submodules}',
                    COALESCE(
                        (
                            SELECT jsonb_object_agg(
                                agent_key,
                                CASE
                                    WHEN jsonb_typeof(agent_value) = 'object' AND agent_value ? 'type' THEN
                                        jsonb_set(
                                            agent_value,
                                            '{type}',
                                            to_jsonb(
                                                CASE
                                                    WHEN agent_value->>'type' IN ('BaseAgentOpenAi', 'BaseAgentGemini', 'BaseAgentGeminiVision') THEN 'AssistantAgent'
                                                    WHEN agent_value->>'type' = 'UserProxyGemini' THEN 'UserProxyAgent'
                                                    ELSE agent_value->>'type'
                                                END
                                            ),
                                            false
                                        )
                                    ELSE agent_value
                                END
                            )
                            FROM jsonb_each(COALESCE(module_value->'submodules', '{}'::jsonb)) AS agent_map(agent_key, agent_value)
                        ),
                        '{}'::jsonb
                    ),
                    false
                )
            ELSE module_value
        END
    )
    FROM jsonb_each(compiled_json) AS module_map(module_key, module_value)
)
WHERE compiled_json IS NOT NULL;

UPDATE agent_ui_template_deployments
SET compiled_json = (
    SELECT jsonb_object_agg(
        module_key,
        CASE
            WHEN jsonb_typeof(module_value) = 'object' AND module_value ? 'submodules' THEN
                jsonb_set(
                    module_value,
                    '{submodules}',
                    COALESCE(
                        (
                            SELECT jsonb_object_agg(
                                agent_key,
                                CASE
                                    WHEN jsonb_typeof(agent_value) = 'object' AND agent_value ? 'type' THEN
                                        jsonb_set(
                                            agent_value,
                                            '{type}',
                                            to_jsonb(
                                                CASE
                                                    WHEN agent_value->>'type' IN ('BaseAgentOpenAi', 'BaseAgentGemini', 'BaseAgentGeminiVision') THEN 'AssistantAgent'
                                                    WHEN agent_value->>'type' = 'UserProxyGemini' THEN 'UserProxyAgent'
                                                    ELSE agent_value->>'type'
                                                END
                                            ),
                                            false
                                        )
                                    ELSE agent_value
                                END
                            )
                            FROM jsonb_each(COALESCE(module_value->'submodules', '{}'::jsonb)) AS agent_map(agent_key, agent_value)
                        ),
                        '{}'::jsonb
                    ),
                    false
                )
            ELSE module_value
        END
    )
    FROM jsonb_each(compiled_json) AS module_map(module_key, module_value)
)
WHERE compiled_json IS NOT NULL;
