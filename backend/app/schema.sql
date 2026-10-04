-- Expense storage. Amounts are integer paise to avoid floating-point rounding errors.
-- CHECK constraints duplicate the API validation so the database stays consistent
-- even if rows are written by another tool.
CREATE TABLE IF NOT EXISTS expenses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT    NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    category       TEXT    NOT NULL CHECK (category IN ('Food', 'Travel', 'Office', 'Software', 'Utilities', 'Marketing', 'Other')),
    description    TEXT    NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 255),
    amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
    payment_method TEXT    NOT NULL CHECK (payment_method IN ('Cash', 'Card', 'UPI', 'Bank Transfer')),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (date);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category);
