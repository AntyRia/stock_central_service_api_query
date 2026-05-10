"""baseline data_query_service auth schema

Revision ID: 001
Revises:
Create Date: 2026-05-10

来源：原 app/schema.py:SCHEMA_SQL（7 张 auth_* 表 + ALTER 补字段 + 索引）。
完整幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON CONFLICT DO NOTHING），
既有 DB 直接 upgrade head NO-OP 通过。

注意：stock_data DB 被多服务共用，本 migration 用独立 version_table=
alembic_version_data_query（见 alembic/env.py:VERSION_TABLE）。
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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

        -- 后续迭代补的字段（ALTER IF NOT EXISTS 幂等）
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
    """)


def downgrade() -> None:
    """破坏性回退：删除全部 auth_* 表。"""
    op.execute("""
        DROP TABLE IF EXISTS auth_token_audit_log CASCADE;
        DROP TABLE IF EXISTS auth_security_event CASCADE;
        DROP TABLE IF EXISTS auth_user_role CASCADE;
        DROP TABLE IF EXISTS auth_token CASCADE;
        DROP TABLE IF EXISTS auth_role CASCADE;
        DROP TABLE IF EXISTS auth_user CASCADE;
    """)
