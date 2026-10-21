CREATE TABLE IF NOT EXISTS transactions (
    id varchar(36) PRIMARY KEY,
    idempotency_key varchar(128) NOT NULL UNIQUE,
    amount_cents integer NOT NULL CHECK (amount_cents > 0),
    description text,
    status varchar(20) NOT NULL DEFAULT 'pending',
    result text,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_transactions_status ON transactions(status);

