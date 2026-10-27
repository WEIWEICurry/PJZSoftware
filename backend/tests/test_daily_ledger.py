"""Synthetic end-to-end API accounting scenarios with independently calculated totals."""

import io
import json
import sqlite3
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pjz.accounting import Accounting
from pjz.api import create_app
from pjz.storage import LedgerStore
from sqlalchemy import text

ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def ledger(tmp_path):
    store = LedgerStore(tmp_path / "daily")
    app = create_app(store, ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        bootstrap = client.post(
            "/api/v1/session/bootstrap",
            json={"token": app.state.session.bootstrap},
            headers={"Origin": ORIGIN},
        )
        headers = {"Origin": ORIGIN, "X-CSRF-Token": bootstrap.json()["csrf_token"]}
        yield store, client, headers
    store.close()


def send(ledger, path, body, method="POST", key=None):
    _, client, headers = ledger
    return client.request(
        method,
        "/api/v1" + path,
        json=body,
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
    )


def account(ledger, name, amount="100000", kind="bank"):
    response = send(
        ledger,
        "/accounts",
        {"name": name, "kind": kind, "opening_date": "2026-01-01", "opening_fen": amount},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def category(ledger, name):
    return next(
        row["id"] for row in ledger[1].get("/api/v1/categories").json() if row["name"] == name
    )


def event(ledger, account_id, amount="3025", kind="expense", **extra):
    body = {
        "kind": kind,
        "account_id": account_id,
        "amount_fen": amount,
        "effective_date": "2026-01-10",
    }
    if kind in ("income", "expense", "refund"):
        body["category_id"] = category(ledger, "工资" if kind == "income" else "餐饮")
    body.update(extra)
    response = send(ledger, "/events", body)
    assert response.status_code == 200, response.text
    return response.json()


def summary(ledger, month="2026-01"):
    return ledger[1].get("/api/v1/summary", params={"month": month}).json()


def test_daily_income_expense_transfer_and_full_backup(ledger):
    store, client, _ = ledger
    bank = account(ledger, "Synthetic bank")
    cash = account(ledger, "Synthetic cash", "0", "cash")
    event(ledger, bank)
    event(ledger, bank, "20000", "income")
    event(
        ledger,
        bank,
        "10000",
        "transfer",
        target_account_id=cash,
        fee_fen="100",
        category_id=category(ledger, "手续费"),
    )
    result = summary(ledger)
    assert result["income_fen"] == "20000"
    assert result["expense_fen"] == "3125"
    assert result["assets_fen"] == "116875"
    assert result["net_fen"] == "116875"
    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM operation_revisions")).scalar() == 5
    snapshot = store.backup()
    restored = LedgerStore(store.restore(snapshot))
    other = Accounting(restored.engine)
    assert other.summary("2026-01-01", "2026-01-31") == result
    assert len(other.events("2026-01-01", "2026-01-31")["items"]) == 5
    restored.close()
    assert client.get("/api/v1/ledger").json()["schema_version"] == 5


def test_idempotency_conflict_and_input_precision(ledger):
    key = str(uuid.uuid4())
    body = {"name": "Synthetic", "kind": "bank", "opening_date": "2026-01-01", "opening_fen": "100"}
    first = send(ledger, "/accounts", body, key=key)
    assert first.status_code == 200
    assert send(ledger, "/accounts", body, key=key).json() == first.json()
    assert send(ledger, "/accounts", {**body, "opening_fen": "101"}, key=key).status_code == 409
    assert len(ledger[1].get("/api/v1/accounts").json()) == 1
    for bad in [0.1, "1.2", "1e2", "1000000000001"]:
        response = send(
            ledger,
            "/events",
            {
                "kind": "income",
                "account_id": first.json()["id"],
                "effective_date": "2026-01-02",
                "category_id": category(ledger, "工资"),
                "amount_fen": bad,
            },
        )
        assert response.status_code == 422
    assert ledger[1].post("/api/v1/accounts", json=body, headers=ledger[2]).status_code == 422


def test_refund_month_and_source_constraints(ledger):
    bank = account(ledger, "Synthetic")
    original = event(ledger, bank, "10000")
    refund = event(
        ledger,
        bank,
        "3000",
        "refund",
        original_event_id=original["id"],
        effective_date="2026-02-01",
    )
    assert summary(ledger)["expense_fen"] == "10000"
    assert summary(ledger, "2026-02")["expense_fen"] == "-3000"
    too_much = {**refund, "amount_fen": "8000"}
    for key in ("id", "status", "revision"):
        too_much.pop(key)
    assert send(ledger, "/events", too_much).status_code == 422
    assert send(ledger, f"/events/{original['id']}/void", {"revision": 1}).status_code == 422
    assert send(ledger, f"/events/{refund['id']}/void", {"revision": 1}).status_code == 200
    assert send(ledger, f"/events/{original['id']}/void", {"revision": 1}).status_code == 200
    assert summary(ledger)["expense_fen"] == "0"


def test_historical_changes_replayed_and_rolled_back(ledger):
    bank = account(ledger, "Synthetic", "0")
    income = event(ledger, bank, "10000", "income", effective_date="2026-01-02")
    expense = event(ledger, bank, "9000", effective_date="2026-01-03")
    assert send(ledger, f"/events/{income['id']}/void", {"revision": 1}).status_code == 422
    updated = {key: value for key, value in expense.items() if key not in ("id", "status")}
    updated["amount_fen"] = "10001"
    assert send(ledger, f"/events/{expense['id']}", updated, "PUT").status_code == 422
    assert ledger[1].get("/api/v1/accounts").json()[0]["balance_fen"] == "1000"
    updated["amount_fen"] = "8000"
    assert send(ledger, f"/events/{expense['id']}", updated, "PUT").status_code == 200
    assert send(ledger, f"/events/{expense['id']}", updated, "PUT").status_code == 409
    assert ledger[1].get("/api/v1/accounts").json()[0]["balance_fen"] == "2000"


def test_debt_borrow_repay_credit_expense_and_adjustment(ledger):
    bank = account(ledger, "Synthetic bank", "0")
    debt = account(ledger, "Synthetic debt", "0", "liability")
    event(
        ledger,
        debt,
        "10000",
        "transfer",
        target_account_id=bank,
        fee_fen="100",
        category_id=category(ledger, "手续费"),
    )
    assert summary(ledger)["net_fen"] == "-100"
    event(ledger, bank, "3000", "transfer", target_account_id=debt)
    event(ledger, debt, "500", "expense")
    assert summary(ledger)["income_fen"] == "0"
    assert summary(ledger)["expense_fen"] == "600"
    assert summary(ledger)["debt_fen"] == "7500"
    assert summary(ledger)["assets_fen"] == "6900"
    event(ledger, bank, "-100", "adjustment", note="Synthetic reconciliation")
    assert summary(ledger)["assets_fen"] == "6800"
    assert summary(ledger)["expense_fen"] == "600"


def test_archiving_and_filtering(ledger):
    bank = account(ledger, "Synthetic", "0")
    categories = ledger[1].get("/api/v1/categories").json()
    assert categories
    archived = send(
        ledger, f"/accounts/{bank}", {"name": "Synthetic", "archived": True, "revision": 1}, "PATCH"
    )
    assert archived.status_code == 200
    assert (
        send(
            ledger,
            "/events",
            {
                "kind": "income",
                "account_id": bank,
                "amount_fen": "1",
                "effective_date": "2026-01-02",
                "category_id": category(ledger, "工资"),
            },
        ).status_code
        == 422
    )
    assert (
        send(
            ledger,
            f"/accounts/{bank}",
            {"name": "Synthetic", "archived": False, "revision": 2},
            "PATCH",
        ).status_code
        == 200
    )
    event(ledger, bank, "100", "income")
    assert (
        send(
            ledger,
            f"/accounts/{bank}",
            {"name": "Synthetic", "archived": True, "revision": 3},
            "PATCH",
        ).status_code
        == 422
    )
    response = ledger[1].get(
        "/api/v1/events",
        params={
            "start": "2026-01-01",
            "end": "2026-01-31",
            "kind": "income",
            "account_id": bank,
            "limit": 1,
        },
    )
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1


def legacy_ledger(path: Path):
    path.mkdir(parents=True)
    with closing(sqlite3.connect(path / "ledger.sqlite3")) as connection:
        connection.execute(
            "CREATE TABLE ledger (id TEXT PRIMARY KEY,name TEXT NOT NULL,"
            "revision INTEGER NOT NULL,created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO ledger VALUES (?,?,?,?)",
            (str(uuid.uuid4()), "Synthetic legacy", 1, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute("PRAGMA user_version=1")
        connection.commit()


def test_legacy_upgrade_and_restore(tmp_path):
    path = tmp_path / "legacy"
    legacy_ledger(path)
    store = LedgerStore(path)
    backups = list((path / "backups").glob("before-v5-*.pjzbackup"))
    assert len(backups) == 1
    with zipfile.ZipFile(io.BytesIO(backups[0].read_bytes())) as package:
        assert json.loads(package.read("manifest.json"))["schema_version"] == 1
    restored = LedgerStore(store.restore(backups[0].read_bytes()))
    assert restored.metadata()["name"] == "Synthetic legacy"
    assert Accounting(restored.engine).accounts() == []
    restored.close()
    store.close()


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    from alembic import command

    path = tmp_path / "legacy"
    legacy_ledger(path)

    def fail(config, revision):
        connection = config.attributes["connection"]
        connection.exec_driver_sql("CREATE TABLE must_rollback (id INTEGER)")
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError, match="Synthetic migration"):
        LedgerStore(path)
    with closing(sqlite3.connect(path / "ledger.sqlite3")) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall() == [("ledger",)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='must_rollback'"
            ).fetchall()
            == []
        )
    assert list((path / "backups").glob("before-v5-*.pjzbackup"))


def test_concurrent_retries_and_stale_revision(ledger):
    from concurrent.futures import ThreadPoolExecutor

    from pjz.domain import RuleError

    store, _, _ = ledger
    service = Accounting(store.engine)
    key = str(uuid.uuid4())
    payload = {
        "name": "Synthetic concurrent",
        "kind": "bank",
        "opening_date": "2026-01-01",
        "opening_fen": "0",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.create_account(payload, key), range(2)))
    assert results[0] == results[1]
    assert len(service.accounts()) == 1
    change = {"name": "Synthetic concurrent renamed", "revision": 1, "archived": False}

    def update(_):
        try:
            service.update_account(results[0]["id"], change, str(uuid.uuid4()))
            return "success"
        except RuleError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, range(2))) == ["REVISION_CONFLICT", "success"]


def test_inconsistent_balance_projection_rejected(ledger):
    from pjz.storage import DataError

    store, _, _ = ledger
    bank = account(ledger, "Synthetic")
    event(ledger, bank)
    with store.engine.begin() as connection:
        connection.execute(text("UPDATE cash_entries SET delta_fen=delta_fen+1"))
    with pytest.raises(DataError, match="INVALID_ACCOUNTING_DATA"):
        store.backup()


def test_future_before_opening_and_negative_fee_rejected(ledger):
    bank = account(ledger, "Synthetic")
    expense = {
        "kind": "expense",
        "account_id": bank,
        "amount_fen": "1",
        "category_id": category(ledger, "餐饮"),
        "effective_date": "9999-01-01",
    }
    assert send(ledger, "/events", expense).status_code == 422
    assert send(ledger, "/events", {**expense, "effective_date": "2025-12-31"}).status_code == 422
    assert (
        send(
            ledger, "/events", {**expense, "effective_date": "2026-01-02", "fee_fen": "-1"}
        ).status_code
        == 422
    )
