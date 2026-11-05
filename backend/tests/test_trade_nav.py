"""Synthetic date migration, provenance and independent performance acceptance."""

import sqlite3

import pytest
from pjz.accounting import Accounting
from pjz.investments import Investments
from pjz.storage import DataError, LedgerStore, validate_database
from sqlalchemy import text
from test_daily_ledger import account, send
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, price, trade
from test_recurring import drafts, generate, row, setup_plan


def test_nav_date_default_validation_edit_and_recurring_identity(ledger):
    plan, cash, asset = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    result = send(
        ledger,
        "/recurring/review",
        {
            "rows": [
                row(drafts(ledger, plan)[0], confirmation_date="2026-01-05", nav_date="2026-01-02")
            ]
        },
    )
    assert result.status_code == 200, result.text
    t = page(ledger)["trades"][0]
    assert (t["is_recurring"], t["nav_date"], t["nav_date_source"]) == (
        True,
        "2026-01-02",
        "recurring",
    )
    result = send(
        ledger,
        "/investments/trades/" + t["id"],
        {
            "account_id": cash,
            "instrument_id": asset,
            "action": "buy",
            "effective_date": "2026-01-05",
            "nav_date": "2026-01-03",
            "quantity": "4.5",
            "amount_fen": "1000",
            "amount_mode": "net",
            "costs_fen": "1",
            "revision": 1,
            "note": "changed note",
        },
        "PUT",
    )
    assert result.status_code == 200, result.text
    assert page(ledger)["trades"][0]["is_recurring"]
    assert drafts(ledger, plan)[0]["nav_date"] == "2026-01-03"
    assert trade(ledger, cash, asset, quantity="1", nav_date="2026-01-11").status_code == 422
    assert (
        trade(ledger, cash, asset, quantity="1", amount_fen="100", costs_fen="0").status_code == 200
    )
    manual = page(ledger)["trades"][0]
    assert manual["nav_date"] == manual["effective_date"] == "2026-01-10"
    assert not manual["is_recurring"]
    with ledger[0].engine.begin() as c:
        c.execute(
            text("UPDATE investment_events SET nav_date='2099-01-01' WHERE event_id=:id"),
            {"id": manual["id"]},
        )
    with pytest.raises(DataError):
        validate_database(ledger[0].path)


def test_v10_backfill_preserves_known_qdii_dates_and_restore(ledger):
    plan, cash, asset = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    assert (
        send(
            ledger,
            "/recurring/review",
            {
                "rows": [
                    row(
                        drafts(ledger, plan)[0],
                        confirmation_date="2026-01-05",
                        nav_date="2026-01-02",
                    )
                ]
            },
        ).status_code
        == 200
    )
    assert (
        trade(ledger, cash, asset, quantity="1", amount_fen="100", costs_fen="0").status_code == 200
    )
    before = page(ledger)["positions"]
    store = ledger[0]
    store.close()
    with sqlite3.connect(store.path) as c:
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0010'")
        c.execute("PRAGMA user_version=10")
    old_backup = store.backup()
    upgraded = LedgerStore(store.directory)
    try:
        current = Investments(Accounting(upgraded.engine)).page()
        assert current["positions"] == before
        records = current["trades"]
        assert [(t["nav_date"], t["nav_date_source"]) for t in records] == [
            ("2026-01-10", "default_backfill"),
            ("2026-01-02", "recurring"),
        ]
        assert list((store.directory / "backups").glob("before-v11-*.pjzbackup"))
        for payload in (old_backup, upgraded.backup()):
            restored = LedgerStore(upgraded.restore(payload))
            try:
                assert Investments(Accounting(restored.engine)).page() == current
            finally:
                restored.close()
    finally:
        upgraded.close()


def test_v11_failed_backfill_is_atomic(ledger, monkeypatch):
    from alembic import op

    store = ledger[0]
    store.close()
    with sqlite3.connect(store.path) as c:
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0010'")
        c.execute("PRAGMA user_version=10")
    original = op.execute

    def fail(statement, *args, **kwargs):
        if "PRAGMA user_version=11" in str(statement):
            raise RuntimeError("synthetic interrupted upgrade")
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(op, "execute", fail)
    with pytest.raises(RuntimeError):
        LedgerStore(store.directory)
    with sqlite3.connect(store.path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 10
        assert "nav_date" not in {r[1] for r in c.execute("PRAGMA table_info(investment_events)")}
    assert list((store.directory / "backups").glob("before-v11-*.pjzbackup"))


def test_position_cumulative_includes_distributions_and_unknowns(ledger):
    cash = account(ledger, "Synthetic cash", "1000000")
    asset = instrument(ledger, "000009", "fund", "FUND")
    assert (
        trade(ledger, cash, asset, quantity="100", amount_fen="10000", costs_fen="0").status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="cash_dividend",
            quantity="0",
            amount_fen="1000",
            costs_fen="0",
            effective_date="2026-01-11",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="reinvest",
            quantity="10",
            amount_fen="1000",
            costs_fen="0",
            effective_date="2026-01-12",
        ).status_code
        == 200
    )
    assert price(ledger, asset, "1.2").status_code == 200
    p = page(ledger)["positions"][0]
    # 110 units * 1.2 = 132; cost 110, holding profit 22; dividends 10+10 => total 42.
    assert (p["holding_return_bps"], p["total_profit_fen"], p["total_return_bps"]) == (
        "2000",
        "4200",
        "4200",
    )
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="sell",
            quantity="110",
            amount_fen="13200",
            costs_fen="0",
            effective_date="2026-01-21",
        ).status_code
        == 200
    )
    closed = page(ledger)["positions"][0]
    assert closed["holding_return_bps"] is None
    assert (closed["total_profit_fen"], closed["total_return_bps"]) == ("4200", "4200")
    unknown = instrument(ledger, "000008", "fund", "FUND")
    assert (
        trade(
            ledger,
            cash,
            unknown,
            action="opening",
            quantity="1",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen=None,
        ).status_code
        == 200
    )
    p = next(p for p in page(ledger)["positions"] if p["instrument_id"] == unknown)
    assert (
        p["holding_return_bps"] is None
        and p["total_profit_fen"] is None
        and p["total_return_bps"] is None
    )
