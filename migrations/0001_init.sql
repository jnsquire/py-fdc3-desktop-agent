-- Migration 0001: Initial schema for FDC3 Desktop Agent
-- Creates tables for app directory, launch configs, and origins

CREATE TABLE IF NOT EXISTS apps (
    app_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT,
    description TEXT,
    icons TEXT,  -- JSON array of icon objects
    intents TEXT  -- JSON array of intent strings
);

CREATE TABLE IF NOT EXISTS launch_configs (
    app_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    args TEXT,  -- JSON array of command arguments
    env TEXT,  -- JSON object of environment variables
    cwd TEXT,  -- Working directory
    timeout INTEGER DEFAULT 30  -- Timeout in seconds for app startup
);

CREATE TABLE IF NOT EXISTS origins (
    app_id TEXT PRIMARY KEY,
    origins TEXT  -- JSON array of allowed origin URLs
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_apps_name ON apps(name);
CREATE INDEX IF NOT EXISTS idx_launch_configs_app_id ON launch_configs(app_id);
CREATE INDEX IF NOT EXISTS idx_origins_app_id ON origins(app_id);