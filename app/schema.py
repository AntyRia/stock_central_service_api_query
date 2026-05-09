from __future__ import annotations

import json
import logging

from .db import Database

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS auth_user (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL DEFAULT '',
  status SMALLINT NOT NULL DEFAULT 1,
  profile JSONB NOT NULL DEFAULT '{}',
  violation_records JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_role (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  description TEXT
);

INSERT INTO auth_role(name, description) VALUES
('admin', '管理员'),
('visitor', '访客')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS auth_user_role (
  user_id UUID NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES auth_role(id) ON DELETE CASCADE,
  PRIMARY KEY(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS auth_token (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token CHAR(64) NOT NULL UNIQUE,
  user_id UUID NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  is_valid BOOLEAN NOT NULL DEFAULT TRUE,
  restore_valid_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  name TEXT,
  banned_until TIMESTAMPTZ,
  ban_reason TEXT,
  ban_detail JSONB NOT NULL DEFAULT '{}',
  last_state_detail JSONB NOT NULL DEFAULT '{}',
  last_status_changed_at TIMESTAMPTZ,
  ban_count INTEGER NOT NULL DEFAULT 0,
  last_banned_at TIMESTAMPTZ,
  issued_via TEXT,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at TIMESTAMPTZ
);

ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS token_scope TEXT NOT NULL DEFAULT 'dashboard';
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER NOT NULL DEFAULT -1;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS rate_limit_per_hour INTEGER NOT NULL DEFAULT -1;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS rate_limit_per_day INTEGER NOT NULL DEFAULT -1;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS quota_max_concurrent INTEGER NOT NULL DEFAULT -1;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS quota_max_queue INTEGER NOT NULL DEFAULT -1;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS allowed_tables JSONB NOT NULL DEFAULT '[]';
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS device_fingerprint_hash TEXT;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS device_fingerprint_bound_at TIMESTAMPTZ;
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS fingerprint_binding_mode TEXT NOT NULL DEFAULT 'optional';
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS token_meta JSONB NOT NULL DEFAULT '{}';
ALTER TABLE auth_token ADD COLUMN IF NOT EXISTS device_rebind_remaining INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_auth_token_scope ON auth_token(token_scope);
CREATE INDEX IF NOT EXISTS idx_auth_token_enabled ON auth_token(enabled);
CREATE INDEX IF NOT EXISTS idx_auth_token_user ON auth_token(user_id);

CREATE TABLE IF NOT EXISTS auth_security_event (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_id UUID REFERENCES auth_token(id) ON DELETE SET NULL,
  user_id UUID REFERENCES auth_user(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  path TEXT,
  detail JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_token_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_id UUID REFERENCES auth_token(id) ON DELETE SET NULL,
  user_id UUID REFERENCES auth_user(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  title TEXT,
  reason_code TEXT,
  detail JSONB NOT NULL DEFAULT '{}',
  operator_type TEXT NOT NULL DEFAULT 'system',
  operator_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def ensure_schema(db: Database) -> None:
    logger.info("ensuring data-query auth schema")
    for statement in [item.strip() for item in SCHEMA_SQL.split(";") if item.strip()]:
        db.execute(statement + ";")
    logger.info("data-query auth schema ready")


def normalize_allowed_tables(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []
