"""Synthetic recurring acceptance: cash, deduplication, migration and restoration."""

import sqlite3
import uuid
from datetime import date

import pytest
from pjz.accounting import Accounting
from pjz.domain import RuleError
from pjz.recurring_domain import schedule
from pjz.storage import DataError, LedgerStore, validate_database
from sqlalchemy import text
from test_daily_ledger import account, send, summary
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, trade


def setup_plan(ledger, amount="1000", cash_amount="100000"):
    cash = account(ledger, "Synthetic recurring cash", cash_amount)
    asset = instrument(ledger, "000001", "fund", "FUND")
    response = send(
        ledger,
        "/recurring",
        {
            "name": "Synthetic daily ten",
            "account_id": cash,
            "instrument_id": asset,
            "start_date": "2026-01-01",
            "frequency": "daily",
            "amount_fen": amount,
            "costs_fen": "1",
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), cash, asset


def generate(ledger, plan, start="2026-01-02", end="2026-01-03"):
    response = send(ledger, f"/recurring/{plan['id']}/generate", {"start": start, "end": end})
    assert response.status_code == 200, response.text
    return response.json()


def drafts(ledger, plan):
    r = ledger[1].get(
        f"/api/v1/recurring/{plan['id']}/drafts",
        params={"start": "2026-01-01", "end": "2026-01-31"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def row(item, **extra):
    return {
        "id": item["id"],
        "revision": item["revision"],
        "decision": "confirm",
        "confirmation_date": item["scheduled_date"],
        "nav_date": item["scheduled_date"],
        "quantity": "4.5",
        "amount_fen": "1000",
        "costs_fen": "1",
        **extra,
    }


def test_atomic_independent_two_ten_yuan_purchases_and_restore(ledger):
    plan, cash, asset = setup_plan(ledger)
    before = summary(ledger)
    assert generate(ledger, plan) == {"count": 2}
    assert generate(ledger, plan) == {"count": 0}
    assert summary(ledger) == before
    assert not page(ledger)["positions"]
    rows = drafts(ledger, plan)
    payload = {"rows": [row(r) for r in rows]}
    key = str(uuid.uuid4())
    result = send(ledger, "/recurring/review", payload, key=key)
    assert result.status_code == 200, result.text
    assert send(ledger, "/recurring/review", payload, key=key).json() == {"count": 2}
    assert send(ledger, "/recurring/review", payload).status_code == 422
    holding = page(ledger)["positions"][0]
    assert holding["quantity"] == "9" and holding["cost_fen"] == "2000"
    with ledger[0].engine.connect() as c:
        balance = next(a for a in Accounting(ledger[0].engine).account_rows(c) if a["id"] == cash)[
            "balance_fen"
        ]
    assert balance == "98000"
    assert summary(ledger)["expense_fen"] == before["expense_fen"]
    assert len(page(ledger)["trades"]) == 2
    assert generate(ledger, plan) == {"count": 0}
    store = ledger[0]
    restored = LedgerStore(store.restore(store.backup()))
    try:
        with restored.engine.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM investment_plans")).scalar_one() == 1
            assert (
                c.execute(
                    text("SELECT COUNT(*) FROM investment_drafts WHERE status='confirmed'")
                ).scalar_one()
                == 2
            )
        assert Accounting(restored.engine).summary("2026-01-01", "2026-01-31") == Accounting(
            store.engine
        ).summary("2026-01-01", "2026-01-31")
    finally:
        restored.close()


def test_insufficient_funds_rolls_back_entire_batch(ledger):
    plan, _, _ = setup_plan(ledger, cash_amount="1500")
    generate(ledger, plan)
    before = summary(ledger)
    response = send(ledger, "/recurring/review", {"rows": [row(r) for r in drafts(ledger, plan)]})
    assert response.status_code == 422, response.text
    assert summary(ledger) == before
    assert all(d["status"] == "pending" and d["revision"] == 1 for d in drafts(ledger, plan))
    assert not page(ledger)["trades"]


def test_pause_resume_skip_and_void_are_not_regenerated(ledger):
    plan, _, _ = setup_plan(ledger)
    assert (
        send(ledger, f"/recurring/{plan['id']}/pause", {"revision": 1, "paused": True}).status_code
        == 200
    )
    assert (
        send(
            ledger,
            f"/recurring/{plan['id']}/generate",
            {"start": "2026-01-02", "end": "2026-01-03"},
        ).status_code
        == 422
    )
    assert (
        send(ledger, f"/recurring/{plan['id']}/pause", {"revision": 1, "paused": False}).status_code
        == 409
    )
    assert (
        send(ledger, f"/recurring/{plan['id']}/pause", {"revision": 2, "paused": False}).status_code
        == 200
    )
    generate(ledger, plan)
    items = drafts(ledger, plan)
    assert (
        send(
            ledger, "/recurring/review", {"rows": [row(items[0], decision="skip"), row(items[1])]}
        ).status_code
        == 200
    )
    confirmed = next(r for r in drafts(ledger, plan) if r["status"] == "confirmed")
    assert (
        send(
            ledger, f"/investments/trades/{confirmed['event_id']}/void", {"revision": 1}
        ).status_code
        == 200
    )
    assert (
        next(r for r in drafts(ledger, plan) if r["status"] == "confirmed")["event_status"]
        == "void"
    )
    assert generate(ledger, plan) == {"count": 0}


def test_possible_manual_duplicate_requires_explicit_override(ledger):
    plan, cash, asset = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    assert (
        trade(
            ledger,
            cash,
            asset,
            quantity="4.5",
            amount_fen="999",
            costs_fen="1",
            effective_date="2026-01-02",
        ).status_code
        == 200
    )
    payload = {"rows": [row(drafts(ledger, plan)[0])]}
    result = send(ledger, "/recurring/review", payload)
    assert result.json()["error"]["code"] == "RECURRING_POSSIBLE_DUPLICATE"
    assert (
        send(ledger, "/recurring/review", {**payload, "allow_possible_duplicate": True}).status_code
        == 200
    )
    assert page(ledger)["positions"][0]["cost_fen"] == "2000"


@pytest.mark.parametrize(
    "fields",
    [
        {"quantity": "0"},
        {"confirmation_date": "2099-01-01"},
        {"confirmation_date": "2026-01-01"},
        {"nav_date": "2026-01-04"},
        {"costs_fen": "1000"},
        {"quantity": "NaN"},
    ],
)
def test_invalid_confirmations_do_not_write(ledger, fields):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    before = page(ledger)
    assert (
        send(
            ledger, "/recurring/review", {"rows": [row(drafts(ledger, plan)[0], **fields)]}
        ).status_code
        == 422
    )
    assert page(ledger) == before
    assert drafts(ledger, plan)[0]["status"] == "pending"


def test_scheduling_independent_dates():
    assert schedule(date(2024, 2, 28), date(2024, 3, 3), date(2024, 1, 1), "weekdays", 0) == [
        "2024-02-28",
        "2024-02-29",
        "2024-03-01",
    ]
    assert schedule(date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 2), "weekly", 0) == [
        "2026-01-05",
        "2026-01-12",
    ]
    with pytest.raises(RuleError):
        schedule(date(2026, 2, 1), date(2026, 1, 1), date(2026, 1, 1), "daily", 0)


def test_duplicate_row_and_archived_account(ledger):
    plan, cash, _ = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    item = row(drafts(ledger, plan)[0])
    assert send(ledger, "/recurring/review", {"rows": [item, item]}).status_code == 422
    with ledger[0].engine.begin() as c:
        c.execute(text("UPDATE accounts SET archived=1 WHERE id=:id"), {"id": cash})
    assert send(ledger, "/recurring/review", {"rows": [item]}).status_code == 422
    assert not page(ledger)["trades"]


def test_restore_rejects_invalid_draft_dates(ledger):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    with ledger[0].engine.begin() as c:
        c.execute(text("UPDATE investment_drafts SET scheduled_date='bad'"))
    with pytest.raises(DataError):
        validate_database(ledger[0].path)


def test_v7_upgrade_preserves_values_and_creates_backup(tmp_path):
    directory = tmp_path / "Synthetic old v7"
    store = LedgerStore(directory)
    store.close()
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        c.execute("DROP TABLE investment_drafts")
        c.execute("DROP TABLE investment_plans")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0007'")
        c.execute("PRAGMA user_version=7")
    upgraded = LedgerStore(directory)
    try:
        assert list((directory / "backups").glob("before-v11-*.pjzbackup"))
        with upgraded.engine.connect() as c:
            assert c.exec_driver_sql("PRAGMA user_version").scalar_one() == 11
            assert c.execute(text("SELECT COUNT(*) FROM investment_plans")).scalar_one() == 0
    finally:
        upgraded.close()


def test_v8_migration_failure_rolls_back_and_keeps_backup(tmp_path, monkeypatch):
    from alembic import op

    directory = tmp_path / "Synthetic migration failure"
    store = LedgerStore(directory)
    store.close()
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        c.execute("DROP TABLE investment_drafts")
        c.execute("DROP TABLE investment_plans")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0007'")
        c.execute("PRAGMA user_version=7")
    original = op.execute

    def fail(statement, *args, **kwargs):
        if "CREATE TABLE investment_drafts" in str(statement):
            raise RuntimeError("synthetic migration interruption")
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(op, "execute", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        LedgerStore(directory)
    assert list((directory / "backups").glob("before-v11-*.pjzbackup"))
    validate_database(directory / "ledger.sqlite3")
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 7
        assert not c.execute(
            "SELECT name FROM sqlite_master WHERE name='investment_plans'"
        ).fetchall()


def test_plan_account_deletion_is_blocked_without_losing_drafts(ledger):
    from pjz.account_deletion import AccountDeletion

    plan, cash, _ = setup_plan(ledger)
    with ledger[0].engine.begin() as c:
        c.execute(text("UPDATE accounts SET archived=1 WHERE id=:id"), {"id": cash})
        c.execute(
            text("UPDATE financial_events SET amount_fen=0 WHERE account_id=:id"), {"id": cash}
        )
        Accounting(ledger[0].engine).rebuild(c)
    with ledger[0].engine.connect() as c:
        with pytest.raises(RuleError, match="RECURRING_ACCOUNT_HAS_PLANS"):
            AccountDeletion(ledger[0]).plan(c, cash)


def test_cash_and_fund_identity_and_future_generation(ledger):
    plan, cash, asset = setup_plan(ledger)
    assert (
        send(
            ledger,
            f"/recurring/{plan['id']}/generate",
            {"start": "2099-01-01", "end": "2099-01-02"},
        ).status_code
        == 422
    )
    debt = account(ledger, "Synthetic debt", "0", "liability")
    payload = {
        "name": "Synthetic invalid",
        "account_id": debt,
        "instrument_id": asset,
        "start_date": "2026-01-01",
        "amount_fen": "1000",
    }
    assert send(ledger, "/recurring", payload).status_code == 422
    assert (
        send(ledger, "/recurring", {**payload, "account_id": cash, "amount_fen": "0"}).status_code
        == 422
    )
    stock = instrument(ledger, "600001", "stock", "SH")
    assert (
        send(
            ledger, "/recurring", {**payload, "account_id": cash, "instrument_id": stock}
        ).status_code
        == 422
    )


def plan_payload(plan, **changes):
    fields = (
        "name",
        "account_id",
        "instrument_id",
        "start_date",
        "frequency",
        "weekday",
        "amount_fen",
        "costs_fen",
        "revision",
    )
    return {**{k: plan[k] for k in fields}, **changes}


def test_edit_plan_preserves_existing_drafts_and_transactions(ledger):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan)
    old = drafts(ledger, plan)
    assert send(ledger, "/recurring/review", {"rows": [row(old[0])]}).status_code == 200
    before = page(ledger)
    result = send(
        ledger,
        f"/recurring/{plan['id']}",
        plan_payload(
            plan, name="Synthetic updated", amount_fen="2000", costs_fen="2", frequency="weekdays"
        ),
        method="PUT",
    )
    assert result.status_code == 200, result.text
    changed = result.json()
    assert changed["revision"] == 2 and changed["has_drafts"]
    assert changed["pending_count"] == 1 and changed["confirmed_count"] == 1
    assert page(ledger) == before
    assert all(d["amount_fen"] == "1000" for d in drafts(ledger, plan))
    generate(ledger, plan, "2026-01-05", "2026-01-05")
    assert (
        next(d for d in drafts(ledger, plan) if d["scheduled_date"] == "2026-01-05")["amount_fen"]
        == "2000"
    )
    assert (
        send(ledger, f"/recurring/{plan['id']}", plan_payload(plan), method="PUT").status_code
        == 409
    )
    assert (
        send(
            ledger,
            f"/recurring/{plan['id']}",
            plan_payload(changed, start_date="2026-01-02"),
            method="PUT",
        ).json()["error"]["code"]
        == "RECURRING_IDENTITY_LOCKED"
    )
    assert (
        send(
            ledger, f"/recurring/{plan['id']}", plan_payload(changed, amount_fen="0"), method="PUT"
        ).status_code
        == 422
    )


def test_paused_delete_hides_plan_keeps_history_and_blocks_all_writes(ledger):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan)
    items = drafts(ledger, plan)
    assert send(ledger, "/recurring/review", {"rows": [row(items[0])]}).status_code == 200
    before = page(ledger)
    path = f"/recurring/{plan['id']}"
    assert (
        send(ledger, path + "/delete", {"revision": 1}).json()["error"]["code"]
        == "RECURRING_DELETE_REQUIRES_PAUSE"
    )
    assert send(ledger, path + "/pause", {"revision": 1, "paused": True}).status_code == 200
    assert send(ledger, path + "/delete", {"revision": 1}).status_code == 409
    key = str(uuid.uuid4())
    assert send(ledger, path + "/delete", {"revision": 2}, key=key).json() == {"count": 1}
    assert send(ledger, path + "/delete", {"revision": 2}, key=key).json() == {"count": 1}
    assert ledger[1].get("/api/v1/recurring").json() == []
    assert ledger[1].get("/api/v1/recurring?include_deleted=true").json()[0]["deleted"]
    assert len(drafts(ledger, plan)) == 2 and page(ledger) == before
    assert (
        send(ledger, path + "/generate", {"start": "2026-01-06", "end": "2026-01-06"}).status_code
        == 422
    )
    assert send(ledger, path + "/pause", {"revision": 3, "paused": False}).status_code == 422
    assert send(ledger, path, plan_payload(plan, revision=3), method="PUT").status_code == 422
    assert send(ledger, "/recurring/review", {"rows": [row(items[1])]}).status_code == 422
    restored = LedgerStore(ledger[0].restore(ledger[0].backup()))
    try:
        with restored.engine.connect() as c:
            assert c.execute(text("SELECT deleted FROM investment_plans")).scalar_one() == 1
            assert c.execute(text("SELECT COUNT(*) FROM investment_drafts")).scalar_one() == 2
    finally:
        restored.close()


def test_qdii_delayed_confirmation_uses_nav_day_not_confirmation_or_latest(ledger):
    from test_investments import price

    plan, _, asset = setup_plan(ledger)
    generate(ledger, plan, "2026-09-30", "2026-09-30")
    path = f"/api/v1/recurring/{plan['id']}/drafts?start=2026-09-30&end=2026-09-30"
    item = ledger[1].get(path).json()[0]
    assert price(ledger, asset, "2.25", "2026-09-30").status_code == 200
    assert price(ledger, asset, "9", "2026-10-12").status_code == 200
    assert price(ledger, asset, "10", "2026-10-30").status_code == 200
    assert (
        send(
            ledger,
            "/recurring/review",
            {
                "rows": [
                    row(
                        item, confirmation_date="2026-10-12", nav_date="2026-09-30", quantity="4.44"
                    )
                ]
            },
        ).status_code
        == 200
    )
    confirmed = ledger[1].get(path).json()[0]
    assert confirmed["nav_price"] == "2.25" and confirmed["effective_date"] == "2026-10-12"
    assert confirmed["nav_date"] == "2026-09-30"
    assert page(ledger)["positions"][0]["quantity"] == "4.44"
    assert page(ledger)["positions"][0]["cost_fen"] == "1000"
    assert price(ledger, asset, "2.25", "2026-09-30", revision=1, status="void").status_code == 200
    assert ledger[1].get(path).json()[0]["nav_price"] is None
    assert page(ledger)["positions"][0]["quantity"] == "4.44"


def test_missing_nav_day_is_rejected_new_confirmation_legacy_is_not_invented(ledger):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan, "2026-01-02", "2026-01-02")
    payload = row(drafts(ledger, plan)[0])
    payload.pop("nav_date")
    assert send(ledger, "/recurring/review", {"rows": [payload]}).status_code == 422
    payload["nav_date"] = "2026-01-02"
    assert send(ledger, "/recurring/review", {"rows": [payload]}).status_code == 200
    with ledger[0].engine.begin() as c:
        c.execute(text("UPDATE investment_drafts SET nav_date=NULL"))
    result = drafts(ledger, plan)[0]
    assert result["nav_date"] is None and result["nav_price"] is None
    validate_database(ledger[0].path)


def test_v8_to_v9_upgrade_preserves_populated_plans_and_drafts(ledger):
    plan, _, _ = setup_plan(ledger)
    generate(ledger, plan)
    store = ledger[0]
    directory = store.directory
    store.close()
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        c.execute("ALTER TABLE investment_plans DROP COLUMN cash_account_id")
        c.execute("ALTER TABLE investment_plans DROP COLUMN deleted")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0008'")
        c.execute("PRAGMA user_version=8")
    upgraded = LedgerStore(directory)
    try:
        assert list((directory / "backups").glob("before-v11-*.pjzbackup"))
        with upgraded.engine.connect() as c:
            assert c.exec_driver_sql("PRAGMA user_version").scalar_one() == 11
            assert (
                c.execute(
                    text("SELECT deleted FROM investment_plans WHERE id=:id"), {"id": plan["id"]}
                ).scalar_one()
                == 0
            )
            assert c.execute(text("SELECT COUNT(*) FROM investment_drafts")).scalar_one() == 2
    finally:
        upgraded.close()


def test_v9_migration_failure_rolls_back_added_column(tmp_path, monkeypatch):
    from alembic import op

    directory = tmp_path / "Synthetic migration9 failure"
    store = LedgerStore(directory)
    store.close()
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        c.execute("ALTER TABLE investment_plans DROP COLUMN cash_account_id")
        c.execute("ALTER TABLE investment_plans DROP COLUMN deleted")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date")
        c.execute("ALTER TABLE investment_events DROP COLUMN nav_date_source")
        c.execute("UPDATE alembic_version SET version_num='0008'")
        c.execute("PRAGMA user_version=8")
    original = op.execute

    def fail(statement, *args, **kwargs):
        if "PRAGMA user_version=9" in str(statement):
            raise RuntimeError("synthetic v9 interruption")
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(op, "execute", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        LedgerStore(directory)
    validate_database(directory / "ledger.sqlite3")
    with sqlite3.connect(directory / "ledger.sqlite3") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 8
        assert "deleted" not in {r[1] for r in c.execute("PRAGMA table_info(investment_plans)")}
