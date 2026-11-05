"""Persist trade NAV dates, preserving known recurring dates and backfill provenance."""

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("ALTER TABLE investment_events ADD COLUMN nav_date TEXT")
    op.execute("ALTER TABLE investment_events ADD COLUMN nav_date_source TEXT")
    op.execute("""UPDATE investment_events SET
        nav_date=COALESCE((SELECT d.nav_date FROM investment_drafts d
            WHERE d.event_id=investment_events.event_id),
            (SELECT f.effective_date FROM financial_events f
            WHERE f.id=investment_events.event_id)),
        nav_date_source=CASE WHEN EXISTS(SELECT 1 FROM investment_drafts d
            WHERE d.event_id=investment_events.event_id AND d.nav_date IS NOT NULL)
            THEN 'recurring' ELSE 'default_backfill' END
        WHERE action IN ('buy','sell')""")
    op.execute("PRAGMA user_version=11")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup into a separate directory.")
