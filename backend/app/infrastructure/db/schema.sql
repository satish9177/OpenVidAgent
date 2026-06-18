CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    script TEXT,
    approved_script TEXT,
    failure_reason TEXT
);
