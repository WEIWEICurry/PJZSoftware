"""Separate holding ownership from recurring cash payment."""

from alembic import op

revision = "0010"
down_revision = "0009"


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
        CHECK(cash_account_id IS NULL OR action IN ('buy','sell','cash_dividend','reinvest')),
        CHECK((action='split')=(split_from_quantity IS NOT NULL))
    )""")
    op.execute("INSERT INTO investment_events_new SELECT * FROM investment_events")
    op.execute("DROP TABLE investment_events")
    op.execute("ALTER TABLE investment_events_new RENAME TO investment_events")
    op.execute(
        "ALTER TABLE investment_plans ADD COLUMN cash_account_id TEXT REFERENCES accounts(id)"
    )
    op.execute("PRAGMA user_version=10")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup into a separate directory.")
