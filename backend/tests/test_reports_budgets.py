"""Independent report and optional-budget scenarios use only synthetic ledgers."""

import csv
import io
import sqlite3
import uuid
from contextlib import closing
from datetime import date

import pytest
from pjz.accounting import Accounting
from pjz.budgets import Budgets
from pjz.domain import RuleError
from pjz.report_domain import calendar_range, report_range
from pjz.reports import Reports
from pjz.storage import DataError, LedgerStore, inspect_backup, validate_database
from test_daily_ledger import account, category, event, send
from test_daily_ledger import ledger as ledger
from test_history_import import commit, preview, seeded_details, source


def report(ledger, period="month", anchor="2026-01-10"):
    response = ledger[1].get("/api/v1/reports", params={"period": period, "anchor": anchor})
    assert response.status_code == 200, response.text
    return response.json()


def budget(ledger, month="2026-01"):
    response = ledger[1].get("/api/v1/budgets/" + month)
    assert response.status_code == 200, response.text
    return response.json()


def set_budget(ledger, limit="10000", month="2026-01", name="餐饮", revision=0, key=None):
    return send(
        ledger,
        "/budgets/" + month + "/" + category(ledger, name),
        {"limit_fen": limit, "revision": revision},
        "PUT",
        key,
    )


@pytest.mark.parametrize(
    "period,anchor,start,end",
    [
        ("day", date(2024, 2, 29), date(2024, 2, 29), date(2024, 2, 29)),
        ("week", date(2025, 1, 1), date(2024, 12, 30), date(2025, 1, 5)),
        ("month", date(2024, 2, 29), date(2024, 2, 1), date(2024, 2, 29)),
        ("year", date(2024, 2, 29), date(2024, 1, 1), date(2024, 12, 31)),
    ],
)
def test_calendar_boundaries(period, anchor, start, end):
    assert calendar_range(period, anchor) == (start, end)


def test_current_period_comparison_and_future():
    bounds = report_range("month", date(2026, 10, 27), date(2026, 10, 27))
    assert bounds["end"] == date(2026, 10, 27)
    assert bounds["calendar_end"] == date(2026, 10, 31)
    assert bounds["previous"] == (date(2026, 9, 1), date(2026, 9, 27))
    week = report_range("week", date(2025, 1, 1), date(2025, 1, 1))
    assert week["previous"] == (date(2024, 12, 23), date(2024, 12, 25))
    leap = report_range("year", date(2024, 2, 29), date(2024, 2, 29))
    assert leap["previous"] == (date(2023, 1, 1), date(2023, 3, 1))
    assert report_range("month", date(2024, 2, 1), date(2026, 1, 1))["previous"] == (
        date(2024, 1, 1),
        date(2024, 1, 31),
    )
    with pytest.raises(RuleError, match="REPORT_FUTURE_PERIOD"):
        report_range("month", date(2026, 11, 1), date(2026, 10, 27))


def test_reports_hand_calculation_fees_refunds_comparison_and_entries(ledger):
    seeded_details(ledger)
    january = report(ledger)
    totals = january["current"]
    assert (
        totals["income_fen"],
        totals["expense_fen"],
        totals["surplus_fen"],
        totals["daily_expense_fen"],
    ) == ("50000", "9100", "40900", "294")
    assert january["changes"][0]["change_bps"] is None
    assert len(january["trend"]) == 31
    dining = next(r for r in totals["categories"] if r["category_name"] == "餐饮")
    assert dining["amount_fen"] == "8300" and dining["share_bps"] == 9121
    daily = report(ledger, "day", "2026-01-12")["current"]
    assert daily["expense_fen"] == "-1900" and daily["surplus_fen"] == "1900"
    weekly = report(ledger, "week", "2026-01-12")["current"]
    assert weekly["start"] == "2026-01-12" and weekly["end"] == "2026-01-18"
    assert weekly["expense_fen"] == "-1900"
    yearly = report(ledger, "year")["current"]
    assert yearly["expense_fen"] == "9100"
    # A prior period with actual income exercises response validation and exact ratio.
    bank = ledger[1].get("/api/v1/accounts").json()[0]["id"]
    event(ledger, bank, "25000", "income", effective_date="2026-02-01")
    february = report(ledger, anchor="2026-02-01")
    assert february["previous"]["income_fen"] == "50000"
    assert february["changes"][0]["delta_fen"] == "-25000"
    assert february["changes"][0]["change_bps"] == "-5000"
    entries = (
        ledger[1]
        .get(
            "/api/v1/reports/entries",
            params={"period": "month", "anchor": "2026-01-10", "limit": 2},
        )
        .json()
    )
    assert entries["total"] == 6 and len(entries["items"]) == 2
    filtered = (
        ledger[1]
        .get(
            "/api/v1/reports/entries",
            params={
                "period": "month",
                "anchor": "2026-01-10",
                "category_id": category(ledger, "餐饮"),
                "direction": "expense",
            },
        )
        .json()
    )
    assert filtered["total"] == 3


def test_history_unknown_daily_weekly_known_monthly_and_direction(ledger):
    seeded_details(ledger)
    assert commit(ledger, preview(ledger, source()).json()).status_code == 200
    day = report(ledger, "day")["current"]
    assert day["income_fen"] == "50000"
    assert day["expense_fen"] is None and day["surplus_fen"] is None
    assert day["known_expense_fen"] == "700"
    weekly = report(ledger, "week")["current"]
    assert weekly["expense_fen"] is None
    month = report(ledger)
    assert month["current"]["expense_fen"] == "16100"
    assert month["trend"][9]["expense_fen"] is None
    assert month["trend"][20]["expense_fen"] == "300"
    assert report(ledger, "year")["trend"][0]["expense_fen"] == "16100"
    items = (
        ledger[1]
        .get("/api/v1/reports/entries", params={"period": "day", "anchor": "2026-01-10"})
        .json()["items"]
    )
    historical = next(r for r in items if r["source"].startswith("历史汇总"))
    assert historical["amount_fen"] == "15000" and historical["counted_fen"] is None
    assert historical["status"] == "unallocated"
    expense = next(r for r in items if r["category_name"] == "餐饮" and r["source"] == "逐笔流水")
    assert expense["status"] == "covered" and expense["counted_fen"] == "0"


def test_principal_adjustments_void_and_empty_reports(ledger):
    bank = account(ledger, "Synthetic bank")
    cash = account(ledger, "Synthetic cash", "0", "cash")
    event(ledger, bank, "1000", "transfer", target_account_id=cash)
    event(ledger, bank, "100", "adjustment", note="Synthetic correction")
    expense = event(ledger, bank, "500")
    assert send(ledger, "/events/" + expense["id"] + "/void", {"revision": 1}).status_code == 200
    value = report(ledger)
    assert value["current"]["income_fen"] == value["current"]["expense_fen"] == "0"
    assert value["current"]["categories"] == []
    assert (
        ledger[1]
        .get("/api/v1/reports", params={"period": "day", "anchor": "2999-01-01"})
        .status_code
        == 422
    )


def test_budget_optional_set_edit_remove_reenable_and_no_cash_change(ledger):
    bank = account(ledger, "Synthetic bank")
    event(ledger, bank, "8000")
    assert budget(ledger)["items"] == []
    balances = ledger[1].get("/api/v1/accounts").json()
    key = str(uuid.uuid4())
    created = set_budget(ledger, key=key)
    assert created.status_code == 200, created.text
    assert set_budget(ledger, key=key).json() == created.json()
    item = budget(ledger)["items"][0]
    assert (
        item["limit_fen"],
        item["used_fen"],
        item["remaining_fen"],
        item["used_bps"],
        item["status"],
    ) == ("10000", "8000", "2000", "8000", "near")
    assert set_budget(ledger, "5000", revision=1).status_code == 200
    item = budget(ledger)["items"][0]
    assert (
        item["remaining_fen"] == "-3000" and item["over_fen"] == "3000" and item["status"] == "over"
    )
    assert set_budget(ledger, None, revision=2).status_code == 200
    removed = budget(ledger)["items"][0]
    assert (
        removed["status"] == "unset"
        and removed["used_fen"] is None
        and removed["remaining_fen"] is None
    )
    assert set_budget(ledger, "9000", revision=3).status_code == 200
    assert ledger[1].get("/api/v1/accounts").json() == balances
    assert budget(ledger, "2026-02")["items"] == []


def test_budget_refund_floor_history_and_future(ledger):
    bank = account(ledger, "Synthetic bank")
    original = event(ledger, bank, "10000", effective_date="2026-01-02")
    event(
        ledger,
        bank,
        "9000",
        "refund",
        effective_date="2026-02-02",
        original_event_id=original["id"],
    )
    assert set_budget(ledger, month="2026-02").status_code == 200
    item = budget(ledger, "2026-02")["items"][0]
    assert (
        item["net_expense_fen"] == "-9000"
        and item["used_fen"] == "0"
        and item["remaining_fen"] == "10000"
    )
    assert commit(ledger, preview(ledger, source()).json()).status_code == 200
    assert set_budget(ledger, "10000").status_code == 200
    assert budget(ledger)["items"][0]["used_fen"] == "15000"
    assert set_budget(ledger, month="2999-01").status_code == 200
    planned = budget(ledger, "2999-01")["items"][0]
    assert planned["status"] == "future" and planned["used_fen"] is None


def test_budget_copy_missing_only_version_retry_and_rollback(ledger, monkeypatch):
    assert set_budget(ledger, "10000").status_code == 200
    assert set_budget(ledger, "20000", name="日用").status_code == 200
    assert set_budget(ledger, "30000", month="2026-02").status_code == 200
    state = budget(ledger, "2026-02")
    key = str(uuid.uuid4())
    payload = {"ledger_revision": state["ledger_revision"]}
    copied = send(ledger, "/budgets/2026-02/copy-previous", payload, key=key)
    assert copied.json() == {"copied": 1}
    assert send(ledger, "/budgets/2026-02/copy-previous", payload, key=key).json() == {"copied": 1}
    values = {row["category_name"]: row["limit_fen"] for row in budget(ledger, "2026-02")["items"]}
    assert values == {"餐饮": "30000", "日用": "20000"}
    assert set_budget(ledger, "1", month="2026-02", revision=0).status_code == 409
    assert send(ledger, "/budgets/2026-02/copy-previous", payload).status_code == 409
    service = Budgets(Accounting(ledger[0].engine))
    before = ledger[0].metadata()

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic rollback")

    monkeypatch.setattr(service.accounting, "rebuild", fail)
    with pytest.raises(RuntimeError):
        service.save("2026-03", category(ledger, "餐饮"), "100", 0, str(uuid.uuid4()))
    assert ledger[0].metadata() == before and budget(ledger, "2026-03")["items"] == []
    with pytest.raises(RuntimeError):
        service.copy_previous("2026-03", before["revision"], str(uuid.uuid4()))
    assert ledger[0].metadata() == before and budget(ledger, "2026-03")["items"] == []


@pytest.mark.parametrize("limit", ["0", "-1", "1.1", "1000000000001", 100])
def test_budget_reject_invalid_limits(ledger, limit):
    assert set_budget(ledger, limit).status_code == 422
    assert budget(ledger)["items"] == []


def test_budget_direction_month_and_large_ratio_precision(ledger):
    assert set_budget(ledger, name="工资").status_code == 422
    assert set_budget(ledger, month="2026-13").status_code == 422
    bank = account(ledger, "Synthetic large", "1000000000000")
    event(ledger, bank, "1000000000000")
    assert set_budget(ledger, "1").status_code == 200
    assert budget(ledger)["items"][0]["used_bps"] == "10000000000000000"


def test_budget_exact_limit_and_csv_export_cap(ledger, monkeypatch):
    bank = account(ledger, "Synthetic bank")
    event(ledger, bank, "4000")
    assert set_budget(ledger, "4000").status_code == 200
    item = budget(ledger)["items"][0]
    assert item["status"] == "exhausted" and item["remaining_fen"] == "0"
    monkeypatch.setattr(Reports, "records", staticmethod(lambda *args: [{}] * 50001))
    with pytest.raises(RuleError, match="REPORT_EXPORT_TOO_LARGE"):
        Reports(Accounting(ledger[0].engine)).export("month", date(2026, 1, 10), None, None)


def test_csv_encoding_formula_protection_and_unknown_values(ledger):
    bank = account(ledger, "=Synthetic bank")
    event(ledger, bank, "100", note=' \t=HYPERLINK("synthetic")')
    assert commit(ledger, preview(ledger, source()).json()).status_code == 200
    response = ledger[1].get(
        "/api/v1/reports/export", params={"period": "day", "anchor": "2026-01-10"}
    )
    assert response.status_code == 200 and response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    original = next(row for row in rows[1:] if row[7] == "逐笔流水")
    assert original[6] == "'=Synthetic bank" and original[8].startswith("'")
    history = next(row for row in rows[1:] if row[7].startswith("历史汇总"))
    assert (
        history[9] == "150.00" and history[10] == "" and history[11] == "原汇总无法分配到所选期间"
    )


def test_budget_backup_restore_and_tampering(ledger, tmp_path):
    store, _, _ = ledger
    assert set_budget(ledger).status_code == 200
    payload = store.backup()
    restored = LedgerStore(store.restore(payload))
    try:
        assert (
            Budgets(Accounting(restored.engine)).get("2026-01")["items"][0]["limit_fen"] == "10000"
        )
    finally:
        restored.close()
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(inspect_backup(payload))
    with closing(sqlite3.connect(damaged)) as connection:
        connection.execute("UPDATE category_budgets SET category_id=?", (category(ledger, "工资"),))
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(DataError):
        validate_database(damaged)


def test_v4_upgrade_failure_rolls_back_budget_table(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from test_simple_loans import legacy_v2

    path = tmp_path / "legacy"
    database = legacy_v2(path)
    engine = create_engine("sqlite:///" + database.as_posix())
    config = Config()
    config.set_main_option("script_location", "backend/pjz/migrations")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        config.attributes["connection"] = connection
        command.upgrade(config, "0004")
        connection.commit()
    engine.dispose()
    original = command.upgrade

    def fail(config, revision):
        original(config, revision)
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        LedgerStore(path)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='category_budgets'"
        ).fetchall()
    assert list((path / "backups").glob("before-v5-*"))
    monkeypatch.setattr(command, "upgrade", original)
    store = LedgerStore(path)
    try:
        assert Accounting(store.engine).accounts()[0]["balance_fen"] == "70000"
        assert Budgets(Accounting(store.engine)).get("2026-01")["items"] == []
    finally:
        store.close()
