"""Schema v8: recurring plans and nonfinancial review drafts."""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""CREATE TABLE investment_plans (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES accounts(id),
        instrument_id TEXT NOT NULL REFERENCES instruments(id), start_date TEXT NOT NULL,
        frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekdays','weekly')),
        weekday INTEGER NOT NULL CHECK(typeof(weekday)='integer' AND weekday BETWEEN 0 AND 6),
        amount_fen INTEGER NOT NULL CHECK(typeof(amount_fen)='integer' AND amount_fen>0),
        costs_fen INTEGER NOT NULL CHECK(typeof(costs_fen)='integer' AND costs_fen>=0
            AND costs_fen<amount_fen),
        paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0), created_at TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE investment_drafts (
        id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES investment_plans(id),
        scheduled_date TEXT NOT NULL,
        amount_fen INTEGER NOT NULL CHECK(typeof(amount_fen)='integer' AND amount_fen>0),
        costs_fen INTEGER NOT NULL CHECK(typeof(costs_fen)='integer' AND costs_fen>=0
            AND costs_fen<amount_fen),
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','skipped','confirmed')),
        event_id TEXT UNIQUE REFERENCES financial_events(id), nav_date TEXT,
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
        UNIQUE(plan_id,scheduled_date), CHECK((status='confirmed')=(event_id IS NOT NULL))
    )""")
    op.execute("PRAGMA user_version=8")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup into a separate directory.")
