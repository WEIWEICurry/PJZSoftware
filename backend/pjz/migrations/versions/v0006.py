"""Investment facts share the chronological financial event stream."""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""CREATE TABLE financial_events_new (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        kind TEXT NOT NULL CHECK(kind IN
        ('opening','income','expense','refund','transfer','adjustment','investment')),
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
    )""")
    op.execute("INSERT INTO financial_events_new SELECT * FROM financial_events")
    op.execute("DROP TABLE financial_events")
    op.execute("ALTER TABLE financial_events_new RENAME TO financial_events")
    op.execute("CREATE INDEX events_date ON financial_events(effective_date,sequence)")
    op.execute("CREATE INDEX events_account ON financial_events(account_id,effective_date)")
    op.execute("CREATE INDEX events_category ON financial_events(category_id,effective_date)")
    op.execute("""CREATE TABLE instruments (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        market TEXT NOT NULL CHECK(market IN ('SH','SZ','BJ','FUND')),
        code TEXT NOT NULL, name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('stock','etf','fund')),
        revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(market,code)
    )""")
    op.execute("""CREATE TABLE investment_events (
        event_id TEXT PRIMARY KEY REFERENCES financial_events(id),
        instrument_id TEXT NOT NULL REFERENCES instruments(id),
        action TEXT NOT NULL CHECK(action IN ('opening','buy','sell')),
        quantity TEXT NOT NULL,
        gross_fen INTEGER NOT NULL CHECK(typeof(gross_fen)='integer' AND gross_fen>=0),
        costs_fen INTEGER NOT NULL CHECK(typeof(costs_fen)='integer' AND costs_fen>=0),
        cost_basis_fen INTEGER CHECK(cost_basis_fen IS NULL OR
            (typeof(cost_basis_fen)='integer' AND cost_basis_fen>=0))
    )""")
    op.execute("""CREATE TABLE valuations (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        instrument_id TEXT NOT NULL REFERENCES instruments(id),
        price_date TEXT NOT NULL, price TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','void')),
        revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(instrument_id,price_date)
    )""")
    op.execute("PRAGMA user_version=6")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
