CREATE TABLE IF NOT EXISTS subscribers (
    subscriber_no TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS monthly_usage (
    subscriber_no TEXT NOT NULL REFERENCES subscribers (subscriber_no),
    bill_year INTEGER NOT NULL CHECK (bill_year >= 1),
    bill_month INTEGER NOT NULL CHECK (bill_month BETWEEN 1 AND 12),
    phone_minutes BIGINT NOT NULL DEFAULT 0 CHECK (phone_minutes >= 0),
    internet_mb BIGINT NOT NULL DEFAULT 0 CHECK (internet_mb >= 0),
    PRIMARY KEY (subscriber_no, bill_year, bill_month)
);

INSERT INTO subscribers (subscriber_no)
SELECT DISTINCT subscriber_no FROM bills
ON CONFLICT DO NOTHING;

INSERT INTO monthly_usage (
    subscriber_no, bill_year, bill_month, phone_minutes, internet_mb
)
SELECT subscriber_no, bill_year, bill_month, phone_minutes, internet_mb
FROM bills
ON CONFLICT DO NOTHING;
