CREATE TABLE IF NOT EXISTS financial_account_preferences (
  pluggy_account_id TEXT PRIMARY KEY,
  display_alias TEXT,
  is_favorite INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
