"""Immutable schema v2: daily accounts, cash events, revision and idempotency."""

from alembic import op

revision = "0002"
down_revision = "0001"

DDL = (
    """CREATE TABLE accounts (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN
        ('cash','bank','payment','securities','liability')), opening_date TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
        revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE categories (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        name TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('income','expense')),
        archived INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(name,direction)
    )""",
    """CREATE TABLE financial_events (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        kind TEXT NOT NULL CHECK(kind IN
        ('opening','income','expense','refund','transfer','adjustment')),
        effective_date TEXT NOT NULL, sequence INTEGER NOT NULL UNIQUE,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        target_account_id TEXT REFERENCES accounts(id),
        category_id TEXT REFERENCES categories(id),
        original_event_id TEXT REFERENCES financial_events(id),
        amount_fen INTEGER NOT NULL CHECK(typeof(amount_fen)='integer'),
        fee_fen INTEGER NOT NULL DEFAULT 0 CHECK(typeof(fee_fen)='integer' AND fee_fen>=0),
        note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','void')), revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE cash_entries (
        event_id TEXT NOT NULL REFERENCES financial_events(id),
        account_id TEXT NOT NULL REFERENCES accounts(id),
        delta_fen INTEGER NOT NULL CHECK(typeof(delta_fen)='integer'),
        PRIMARY KEY(event_id,account_id)
    )""",
    """CREATE TABLE operation_revisions (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        entity_id TEXT NOT NULL, operation TEXT NOT NULL, before_json TEXT,
        after_json TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    """CREATE TABLE idempotency_records (
        key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
        result_json TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX events_date ON financial_events(effective_date,sequence)",
    "CREATE INDEX events_account ON financial_events(account_id,effective_date)",
    "CREATE INDEX events_category ON financial_events(category_id,effective_date)",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute("PRAGMA user_version=2")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
