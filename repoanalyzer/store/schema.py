SCHEMA_VERSION = 2

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS schema_migrations(
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS index_metadata(
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY,
  language TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  line_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS file_index(
  path TEXT PRIMARY KEY,
  language TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  line_count INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL DEFAULT 'indexed'
);

CREATE TABLE IF NOT EXISTS facts(
  fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  subject TEXT,
  predicate TEXT,
  object TEXT,
  symbol TEXT,
  qualified_name TEXT,
  kind TEXT,
  caller TEXT,
  callee TEXT,
  call_kind TEXT,
  route_json TEXT NOT NULL DEFAULT '[]',
  confidence TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_facts_symbol ON facts(symbol);
CREATE INDEX IF NOT EXISTS idx_facts_qualified_name ON facts(qualified_name);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(object);
CREATE INDEX IF NOT EXISTS idx_facts_caller ON facts(caller);
CREATE INDEX IF NOT EXISTS idx_facts_callee ON facts(callee);
CREATE INDEX IF NOT EXISTS idx_facts_path ON facts(path);
CREATE INDEX IF NOT EXISTS idx_facts_type_path ON facts(fact_type, path);
CREATE INDEX IF NOT EXISTS idx_facts_build_status ON facts(json_extract(payload_json, '$.build_status'));
CREATE INDEX IF NOT EXISTS idx_file_index_status ON file_index(status);
CREATE INDEX IF NOT EXISTS idx_file_index_source_kind ON file_index(source_kind);
"""
