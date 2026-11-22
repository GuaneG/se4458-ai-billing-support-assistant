ALTER TABLE bills
    ADD COLUMN IF NOT EXISTS public_summary BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS payments (
    transaction_id TEXT PRIMARY KEY,
    subscriber_no TEXT NOT NULL,
    bill_year INTEGER NOT NULL,
    bill_month INTEGER NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    FOREIGN KEY (subscriber_no, bill_year, bill_month)
        REFERENCES bills (subscriber_no, bill_year, bill_month)
);
