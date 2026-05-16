DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE 'interactions\_%' ESCAPE '\'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', rec.table_name);
    END LOOP;

    EXECUTE 'DROP TABLE IF EXISTS public.decipher_auditor_agent_data CASCADE';
END $$;
