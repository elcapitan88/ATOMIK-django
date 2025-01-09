-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    username VARCHAR UNIQUE NOT NULL,
    hashed_password VARCHAR NOT NULL,
    is_active BOOLEAN DEFAULT true,
    is_superuser BOOLEAN DEFAULT false
);

-- Create webhooks table
CREATE TABLE IF NOT EXISTS webhooks (
    id SERIAL PRIMARY KEY,
    token UUID UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255),
    details TEXT,
    secret_key VARCHAR(64) NOT NULL,
    source_type VARCHAR(50) DEFAULT 'custom',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_triggered TIMESTAMP,
    allowed_ips TEXT,
    max_triggers_per_minute INTEGER DEFAULT 60,
    require_signature BOOLEAN DEFAULT true,
    max_retries INTEGER DEFAULT 3,
    retry_interval INTEGER DEFAULT 60
);

-- Create webhook_logs table
CREATE TABLE IF NOT EXISTS webhook_logs (
    id SERIAL PRIMARY KEY,
    webhook_id INTEGER REFERENCES webhooks(id) ON DELETE CASCADE,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT true,
    payload TEXT,
    error_message TEXT,
    ip_address VARCHAR(45),
    processing_time FLOAT
);