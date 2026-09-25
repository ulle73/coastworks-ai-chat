CREATE TABLE bot_billing (
 bot_id uuid PRIMARY KEY REFERENCES bots(id) ON DELETE RESTRICT,
 customer_id text UNIQUE,
 subscription_id text UNIQUE,
 status text NOT NULL DEFAULT 'none',
 paid_until timestamptz,
 cancel_at_period_end boolean NOT NULL DEFAULT false,
 checked_at timestamptz,
 checkout_attempt uuid,
 checkout_expires_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE billing_events (
 event_id text PRIMARY KEY,
 customer_id text NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(),
 processed_at timestamptz,
 attempts int NOT NULL DEFAULT 0,
 retry_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pending_billing_events ON billing_events(retry_at) WHERE processed_at IS NULL;
