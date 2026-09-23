CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE bots (
 id uuid PRIMARY KEY, url text NOT NULL, origin text NOT NULL,
 preview_hash text NOT NULL, owner_email text,
 state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','reading','checking','ready','failed')),
 error_code text, active_version uuid, quality jsonb NOT NULL DEFAULT '{}',
 install_nonce text NOT NULL, published boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 refreshed_at timestamptz, CHECK (NOT published OR (owner_email IS NOT NULL AND active_version IS NOT NULL))
);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','done','failed')),
 attempts int NOT NULL DEFAULT 0, lease_token uuid, lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, error_code text
);
CREATE UNIQUE INDEX one_active_job_per_bot ON jobs(bot_id) WHERE state IN ('queued','running');
CREATE INDEX job_queue ON jobs(state, created_at);
CREATE TABLE chunks (
 bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 version uuid NOT NULL, ordinal int NOT NULL, url text NOT NULL, title text NOT NULL,
 content text NOT NULL, embedding vector NOT NULL, embedding_model text NOT NULL,
 PRIMARY KEY(bot_id, version, ordinal)
);
CREATE TABLE email_tokens (
 token_hash text PRIMARY KEY, bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 email text NOT NULL, expires_at timestamptz NOT NULL, used_at timestamptz
);
CREATE TABLE messages (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 session_hash text NOT NULL, role text NOT NULL CHECK(role IN ('user','assistant')),
 content text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversation ON messages(bot_id, session_hash, id DESC);
CREATE TABLE rate_limits (key text PRIMARY KEY, count int NOT NULL, expires_at timestamptz NOT NULL);
CREATE TABLE managed_requests (
 id uuid PRIMARY KEY, email text NOT NULL, website text NOT NULL, message text NOT NULL,
 state text NOT NULL DEFAULT 'new' CHECK(state IN ('new','contacted','onboarding','active','closed')),
 created_at timestamptz NOT NULL DEFAULT now()
);
