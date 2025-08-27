-- Create test table for CDC testing
CREATE TABLE test (
    id SERIAL PRIMARY KEY,
    description TEXT
);

-- Insert some initial test data
INSERT INTO test (description) VALUES 
    ('Initial test record 1'),
    ('Initial test record 2'),
    ('Initial test record 3');