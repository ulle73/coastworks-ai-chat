CREATE TABLE managed_sources (
 id uuid PRIMARY KEY, bot_id uuid NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 title text NOT NULL, source_url text NOT NULL, content text NOT NULL,
 approved_public boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX managed_sources_bot ON managed_sources(bot_id);
