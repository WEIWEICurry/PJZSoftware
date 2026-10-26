"""Existing M0 ledger metadata baseline; created by the bootstrap."""

revision = "0001"
down_revision = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of downgrading.")
