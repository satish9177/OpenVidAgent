CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    script TEXT,
    approved_script TEXT,
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    uri TEXT NOT NULL,
    metadata TEXT NOT NULL,
    UNIQUE (run_id, kind, version)
);

CREATE INDEX IF NOT EXISTS idx_assets_run_kind ON assets (run_id, kind);
