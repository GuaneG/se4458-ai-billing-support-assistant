# Billing data model

```mermaid
erDiagram
    subscribers ||--o{ monthly_usage : records
    subscribers ||..o{ bills : owns
    monthly_usage |o..o| bills : matches_period
    bills ||..o{ payments : receives

    subscribers {
        text subscriber_no PK
    }

    monthly_usage {
        text subscriber_no PK, FK
        integer bill_year PK
        integer bill_month PK
        bigint phone_minutes
        bigint internet_mb
    }

    bills {
        text subscriber_no PK
        integer bill_year PK
        integer bill_month PK
        integer phone_minutes
        integer internet_mb
        bigint phone_charge_cents
        bigint internet_charge_cents
        bigint paid_cents
        boolean public_summary
    }

    payments {
        text transaction_id PK
        text subscriber_no FK
        integer bill_year FK
        integer bill_month FK
        bigint amount_cents
    }

    operator_accounts {
        text username PK
        bytea password_salt
        bytea password_hash
    }
```

- PostgreSQL enforces the foreign key from `monthly_usage.subscriber_no`
  to `subscribers.subscriber_no` and the composite foreign key from
  `payments` to the corresponding bill. `bills` identifies the subscriber
  and period at the application level. It shares those three key fields
  with `monthly_usage`.
- `monthly_usage` holds current counters. `bills` stores the usage snapshot
  and charges from the latest calculation for that period. Payment records
  have unique transaction IDs. Recording a payment and updating
  `bills.paid_cents` happen in one database transaction.
- `public_summary` marks synthetic bills that allow anonymous summary
  queries. `operator_accounts` stores salted password hashes separately
  from subscriber records. Chat keeps pending confirmations in process
  memory until use or expiry.

[Bill schema](../billing_api/db/schema.sql) ·
[Subscriber and usage schema](../billing_api/db/usage.sql) ·
[Payment and public summary schema](../billing_api/db/payments.sql) ·
[Operator account schema](../billing_api/db/operator_accounts.sql)
