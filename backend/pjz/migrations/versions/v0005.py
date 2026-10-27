"""Optional monthly category budgets; removal preserves concurrency revisions."""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""CREATE TABLE category_budgets (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        month TEXT NOT NULL, category_id TEXT NOT NULL REFERENCES categories(id),
        limit_fen INTEGER CHECK(limit_fen IS NULL OR
            (typeof(limit_fen)='integer' AND limit_fen>0 AND limit_fen<=1000000000000)),
        revision INTEGER NOT NULL CHECK(revision>0),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(month,category_id)
    )""")
    op.execute("PRAGMA user_version=5")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
