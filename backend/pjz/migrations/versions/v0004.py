"""Schema v4: source-preserving historical summaries, separate from cash events."""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("""CREATE TABLE import_batches (
        id TEXT PRIMARY KEY, ledger_id TEXT NOT NULL REFERENCES ledger(id),
        filename TEXT NOT NULL, file_hash TEXT NOT NULL, canonical_hash TEXT NOT NULL,
        source_blob BLOB NOT NULL, mapping_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','withdrawn')),
        revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE historical_summaries (
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES import_batches(id),
        period_start TEXT NOT NULL, period_end TEXT NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('income','expense')),
        category_id TEXT NOT NULL REFERENCES categories(id), source_category TEXT NOT NULL,
        amount_fen INTEGER NOT NULL CHECK(typeof(amount_fen)='integer' AND amount_fen>=0),
        source_refs_json TEXT NOT NULL
    )""")
    op.execute(
        "CREATE UNIQUE INDEX active_import_file ON import_batches(file_hash) WHERE status='active'"
    )
    op.execute(
        "CREATE UNIQUE INDEX active_import_content ON import_batches(canonical_hash) "
        "WHERE status='active'"
    )
    op.execute(
        "CREATE INDEX history_coverage ON historical_summaries(category_id,period_start,period_end)"
    )
    op.execute("PRAGMA user_version=4")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
