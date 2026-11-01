"""Schema v9: hide deleted plans while retaining immutable transaction associations."""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE investment_plans ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 "
        "CHECK(deleted IN (0,1))"
    )
    op.execute("PRAGMA user_version=9")


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup into a separate directory.")
