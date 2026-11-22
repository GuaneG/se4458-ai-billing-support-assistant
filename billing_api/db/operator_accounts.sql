CREATE TABLE IF NOT EXISTS operator_accounts (
    username TEXT PRIMARY KEY CHECK (length(username) BETWEEN 3 AND 64 AND username <> 'a001'),
    password_salt BYTEA NOT NULL CHECK (octet_length(password_salt) = 16),
    password_hash BYTEA NOT NULL CHECK (octet_length(password_hash) = 64)
);
