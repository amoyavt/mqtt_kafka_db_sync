-- IoT Replica Database Schema
-- This file initializes the PostgreSQL database for the IoT replica device

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set performance optimizations for IoT device
SET shared_preload_libraries = 'pg_stat_statements';
SET log_statement = 'none';  -- Reduce logging for performance
SET log_min_duration_statement = 1000;  -- Log only slow queries

-- Create sync metadata table to track synchronization state
CREATE TABLE IF NOT EXISTS _sync_metadata (
    table_name VARCHAR(255) PRIMARY KEY,
    last_sync_timestamp BIGINT NOT NULL,
    total_records INTEGER DEFAULT 0,
    last_error TEXT DEFAULT NULL,
    sync_status VARCHAR(20) DEFAULT 'active' 
        CHECK (sync_status IN ('active', 'paused', 'error')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create sync log table for debugging and monitoring
CREATE TABLE IF NOT EXISTS _sync_log (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) NOT NULL,
    operation VARCHAR(20) NOT NULL 
        CHECK (operation IN ('insert', 'update', 'delete', 'error')),
    record_id TEXT,
    timestamp BIGINT NOT NULL,
    payload JSONB, -- JSON payload for debugging
    error_message TEXT DEFAULT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_sync_log_table_timestamp 
ON _sync_log (table_name, timestamp);

CREATE INDEX IF NOT EXISTS idx_sync_log_processed_at 
ON _sync_log (processed_at);

CREATE INDEX IF NOT EXISTS idx_sync_log_operation 
ON _sync_log (operation);

-- Create index on JSONB payload for efficient queries
CREATE INDEX IF NOT EXISTS idx_sync_log_payload_gin 
ON _sync_log USING gin (payload);

-- Create trigger to update sync metadata updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_sync_metadata_updated_at 
    BEFORE UPDATE ON _sync_metadata 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create views for monitoring and reporting

-- View to show sync status for all tables
CREATE OR REPLACE VIEW v_sync_status AS
SELECT 
    table_name,
    total_records,
    to_timestamp(last_sync_timestamp/1000) as last_sync_time,
    sync_status,
    last_error,
    updated_at as last_updated
FROM _sync_metadata
ORDER BY last_sync_timestamp DESC;

-- View to show recent sync activity (last 24 hours)
CREATE OR REPLACE VIEW v_recent_sync_activity AS
SELECT 
    table_name,
    operation,
    COUNT(*) as operation_count,
    to_timestamp(MAX(timestamp)/1000) as last_operation_time
FROM _sync_log 
WHERE processed_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY table_name, operation
ORDER BY last_operation_time DESC;

-- View to show sync errors (last 100 errors)
CREATE OR REPLACE VIEW v_sync_errors AS
SELECT 
    table_name,
    operation,
    error_message,
    processed_at as error_time,
    payload
FROM _sync_log 
WHERE error_message IS NOT NULL
ORDER BY processed_at DESC
LIMIT 100;

-- View to show sync performance metrics
CREATE OR REPLACE VIEW v_sync_performance AS
SELECT 
    table_name,
    DATE_TRUNC('hour', processed_at) as hour,
    operation,
    COUNT(*) as operations_count,
    AVG(EXTRACT(EPOCH FROM (processed_at - to_timestamp(timestamp/1000)))) as avg_processing_delay_seconds
FROM _sync_log
WHERE processed_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY table_name, DATE_TRUNC('hour', processed_at), operation
ORDER BY hour DESC, table_name, operation;

-- Function to cleanup old sync logs (keep only last 7 days)
CREATE OR REPLACE FUNCTION cleanup_sync_logs()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM _sync_log 
    WHERE processed_at < CURRENT_TIMESTAMP - INTERVAL '7 days';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    INSERT INTO _sync_log (table_name, operation, timestamp, payload, processed_at)
    VALUES ('_sync_log', 'cleanup', EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) * 1000, 
            json_build_object('deleted_records', deleted_count)::jsonb, CURRENT_TIMESTAMP);
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Create a scheduled cleanup job (requires pg_cron extension in production)
-- SELECT cron.schedule('cleanup-sync-logs', '0 2 * * *', 'SELECT cleanup_sync_logs();');

-- Example table structures (will be created dynamically by the sync service)
-- These are just for reference

/*
-- Example users table that might be replicated
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Example products table that might be replicated  
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10,2),
    category VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add update triggers for replicated tables
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_products_updated_at 
    BEFORE UPDATE ON products 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
*/

-- Grant permissions for replica user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO replica;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO replica;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO replica;

-- Grant permissions for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO replica;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO replica;