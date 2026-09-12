CREATE TABLE IF NOT EXISTS cpu_metrics (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cpu_percent NUMERIC(5,2) NOT NULL,
    per_core JSONB NOT NULL,
    cpu_frequency_mhz NUMERIC(10,2),
    memory_percent NUMERIC(5,2) NOT NULL,
    process_count INTEGER NOT NULL,
    disk_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
    disk_used_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
    disk_free_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
    disk_total_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_upload_kbps NUMERIC(12,2) NOT NULL DEFAULT 0,
    net_download_kbps NUMERIC(12,2) NOT NULL DEFAULT 0,
    net_sent_mb NUMERIC(14,2) NOT NULL DEFAULT 0,
    net_recv_mb NUMERIC(14,2) NOT NULL DEFAULT 0
);

ALTER TABLE cpu_metrics
ADD COLUMN IF NOT EXISTS disk_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS disk_used_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS disk_free_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS disk_total_gb NUMERIC(10,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS net_upload_kbps NUMERIC(12,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS net_download_kbps NUMERIC(12,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS net_sent_mb NUMERIC(14,2) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS net_recv_mb NUMERIC(14,2) NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_cpu_metrics_recorded_at
ON cpu_metrics (recorded_at DESC);

CREATE TABLE IF NOT EXISTS application_activity (
    id BIGSERIAL PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_name TEXT NOT NULL,
    pid INTEGER NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE application_activity
ADD COLUMN IF NOT EXISTS first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS sample_count INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_application_activity_last_seen
ON application_activity (last_seen DESC);

CREATE INDEX IF NOT EXISTS idx_application_activity_process_name
ON application_activity (process_name);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username
ON users (username);

CREATE INDEX IF NOT EXISTS idx_users_email
ON users (email);

CREATE TABLE IF NOT EXISTS notification_logs (
    id BIGSERIAL PRIMARY KEY,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id BIGINT,
    recipient_email TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT 'gmail',
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT NOT NULL DEFAULT ''
);

ALTER TABLE notification_logs
ADD COLUMN IF NOT EXISTS user_id BIGINT,
ADD COLUMN IF NOT EXISTS recipient_email TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_notification_logs_sent_at
ON notification_logs (sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_logs_user_sent_at
ON notification_logs (user_id, sent_at DESC);
