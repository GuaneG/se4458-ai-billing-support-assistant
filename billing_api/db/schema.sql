CREATE TABLE bills (
    subscriber_no TEXT NOT NULL,
    bill_year INTEGER NOT NULL CHECK (bill_year >= 1),
    bill_month INTEGER NOT NULL CHECK (bill_month BETWEEN 1 AND 12),
    phone_minutes INTEGER NOT NULL CHECK (phone_minutes >= 0),
    internet_mb INTEGER NOT NULL CHECK (internet_mb >= 0),
    phone_charge_cents BIGINT NOT NULL CHECK (phone_charge_cents >= 0),
    internet_charge_cents BIGINT NOT NULL CHECK (internet_charge_cents >= 0),
    paid_cents BIGINT NOT NULL DEFAULT 0
        CHECK (paid_cents BETWEEN 0 AND phone_charge_cents + internet_charge_cents),
    PRIMARY KEY (subscriber_no, bill_year, bill_month)
);
