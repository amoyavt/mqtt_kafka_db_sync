-- Runs once on first init (new, empty data dir).
-- Creates a replication user for Debezium with access to ALL schemas and tables.

CREATE ROLE debezium WITH LOGIN REPLICATION PASSWORD 'debezium_secure_password';

-- Grant access to ALL existing and future schemas
DO $$
DECLARE
    schema_name text;
BEGIN
    -- Grant usage on all existing schemas
    FOR schema_name IN 
        SELECT nspname FROM pg_namespace 
        WHERE nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
        AND nspname NOT LIKE 'pg_temp_%' AND nspname NOT LIKE 'pg_toast_temp_%'
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO debezium', schema_name);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO debezium', schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO debezium', schema_name);
    END LOOP;
END $$;

-- Additional permissions needed for Debezium to manage publications and replication slots
-- Note: CREATE permission is needed only for publication management, not for data modification
GRANT CREATE ON DATABASE appdb TO debezium;

-- Create publication for ALL TABLES (Debezium will use this)
CREATE PUBLICATION dbz_publication FOR ALL TABLES;
