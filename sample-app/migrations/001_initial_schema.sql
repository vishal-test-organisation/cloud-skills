-- Initial schema for CloudSkills SaaS platform
-- User data stored without encryption markers
-- Retention policy not enforced at DB level

CREATE TABLE users (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email       VARCHAR(255) NOT NULL UNIQUE,
  first_name  VARCHAR(100),
  last_name   VARCHAR(100),
  phone       VARCHAR(30),
  date_of_birth DATE,          -- collected at signup, never used
  ip_address  VARCHAR(45),     -- stored permanently, no retention
  user_agent  TEXT,            -- stored permanently, no retention
  password_hash TEXT NOT NULL,
  is_deleted  BOOLEAN DEFAULT false,  -- soft delete only — GDPR gap
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE user_sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users(id),
  session_token TEXT NOT NULL,
  ip_address  VARCHAR(45),
  created_at  TIMESTAMPTZ DEFAULT now(),
  expires_at  TIMESTAMPTZ
  -- no cleanup job — sessions accumulate forever
);

CREATE TABLE audit_logs (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID REFERENCES users(id),
  action      VARCHAR(100),
  resource    VARCHAR(255),
  -- Stores full request body including PII — GDPR + SOC2 gap
  request_payload JSONB,
  ip_address  VARCHAR(45),
  created_at  TIMESTAMPTZ DEFAULT now()
  -- no retention policy, no purge job
);

CREATE TABLE consent_records (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users(id),
  purpose     VARCHAR(100),
  consented   BOOLEAN,
  created_at  TIMESTAMPTZ DEFAULT now()
  -- missing: consent version, UI element, withdrawal timestamp
);

CREATE TABLE support_tickets (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users(id),
  subject     TEXT,
  body        TEXT,       -- may contain PII typed by user
  status      VARCHAR(50),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- No data retention enforcement, no automated purge jobs
-- No hard-delete cascade when user account is deleted
-- No encryption-at-rest markers on sensitive columns
