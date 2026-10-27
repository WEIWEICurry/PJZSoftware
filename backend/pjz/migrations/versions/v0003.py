"""Schema v3: receivable principal accounts, preserving every existing row."""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    # The store disables FK enforcement before BEGIN; it checks all FKs before commit.
    op.execute("""CREATE TABLE accounts_new (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN
        ('cash','bank','payment','securities','liability','receivable')),
        opening_date TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
        revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    op.execute("INSERT INTO accounts_new SELECT * FROM accounts")
    op.execute("DROP TABLE accounts")
    op.execute("ALTER TABLE accounts_new RENAME TO accounts")
    op.execute("PRAGMA user_version=3")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
