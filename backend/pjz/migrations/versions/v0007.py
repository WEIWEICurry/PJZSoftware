"""Schema v7: distributions and confirmed before/after unit conversions."""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""CREATE TABLE investment_events_new (
        event_id TEXT PRIMARY KEY REFERENCES financial_events(id),
        instrument_id TEXT NOT NULL REFERENCES instruments(id),
        action TEXT NOT NULL CHECK(action IN
            ('opening','buy','sell','cash_dividend','reinvest','split')),
        quantity TEXT NOT NULL,
        gross_fen INTEGER NOT NULL CHECK(typeof(gross_fen)='integer' AND gross_fen>=0),
        costs_fen INTEGER NOT NULL CHECK(typeof(costs_fen)='integer' AND costs_fen>=0),
        cost_basis_fen INTEGER CHECK(cost_basis_fen IS NULL OR
            (typeof(cost_basis_fen)='integer' AND cost_basis_fen>=0)),
        cash_account_id TEXT REFERENCES accounts(id), split_from_quantity TEXT,
        CHECK(cash_account_id IS NULL OR action='cash_dividend'),
        CHECK((action='split')=(split_from_quantity IS NOT NULL))
    )""")
    op.execute("""INSERT INTO investment_events_new
        (event_id,instrument_id,action,quantity,gross_fen,costs_fen,cost_basis_fen)
        SELECT event_id,instrument_id,action,quantity,gross_fen,costs_fen,cost_basis_fen
        FROM investment_events""")
    op.execute("DROP TABLE investment_events")
    op.execute("ALTER TABLE investment_events_new RENAME TO investment_events")
    op.execute("PRAGMA user_version=7")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
