"""Packaged executable acceptance probe, using only temporary synthetic data."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from pjz.account_deletion import AccountDeletion
from pjz.accounting import Accounting
from pjz.api import create_app
from pjz.budgets import Budgets
from pjz.history import HistoryImports
from pjz.reports import Reports
from pjz.storage import LedgerStore, inspect_backup


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="PJZ-中文-") as temporary:
        directory = Path(temporary) / "测试账本"
        store = LedgerStore(directory)
        original = store.metadata()
        store.rename("Synthetic acceptance ledger", original["revision"])
        accounting = Accounting(store.engine)
        account = accounting.create_account(
            {
                "name": "Synthetic packaged account",
                "kind": "bank",
                "opening_date": "2026-01-01",
                "opening_fen": "10000",
            },
            str(uuid.uuid4()),
        )
        expense_category = next(
            item["id"] for item in accounting.categories() if item["name"] == "餐饮"
        )
        accounting.create_event(
            {
                "kind": "expense",
                "effective_date": "2026-01-02",
                "account_id": account["id"],
                "amount_fen": "3025",
                "fee_fen": "0",
                "category_id": expense_category,
                "target_account_id": None,
                "original_event_id": None,
                "note": "Synthetic packaged expense",
            },
            str(uuid.uuid4()),
        )
        assert accounting.summary("2026-01-01", "2026-01-31")["assets_fen"] == "6975"
        assert accounting.note_suggestions(expense_category) == [
            {"note": "Synthetic packaged expense", "count": 1}
        ]
        disposable = accounting.create_account(
            {
                "name": "Synthetic packaged discarded",
                "kind": "cash",
                "opening_date": "2026-01-01",
                "opening_fen": "0",
            },
            str(uuid.uuid4()),
        )
        accounting.update_account(
            disposable["id"],
            {
                "name": "Synthetic packaged discarded",
                "archived": True,
                "revision": 1,
            },
            str(uuid.uuid4()),
        )
        deletion = AccountDeletion(store)
        preview = deletion.preview(disposable["id"])
        deleted = deletion.commit(
            disposable["id"],
            {
                "preview_token": preview["preview_token"],
                "confirm_name": "Synthetic packaged discarded",
            },
            str(uuid.uuid4()),
        )
        assert deleted["deleted"] and len(accounting.accounts()) == 1
        loan = accounting.record_loan(
            {
                "action": "lend",
                "cash_account_id": account["id"],
                "counterparty_name": "Synthetic packaged borrower",
                "counterparty_id": None,
                "effective_date": "2026-01-03",
                "amount_fen": "1000",
                "note": "",
            },
            str(uuid.uuid4()),
        )
        accounting.record_loan(
            {
                "action": "collect",
                "cash_account_id": account["id"],
                "counterparty_id": loan["target_account_id"],
                "counterparty_name": None,
                "effective_date": "2026-01-04",
                "amount_fen": "500",
                "note": "",
            },
            str(uuid.uuid4()),
        )
        totals = accounting.summary("2026-01-01", "2026-01-31")
        assert totals["receivable_fen"] == "500" and totals["net_fen"] == "6975"
        historical = HistoryImports(accounting)
        historical_source = json.dumps(
            {
                "schema_version": 1,
                "currency": "CNY",
                "amount_unit": "fen",
                "record_type": "monthly_category_expense_summary",
                "periods": [
                    {
                        "start_date": "2026-01-01",
                        "end_date": "2026-01-20",
                        "displayed_total_fen": 4000,
                        "source_images": ["synthetic-source.png"],
                        "categories": [{"category": "餐饮", "amount_fen": 4000}],
                    }
                ],
            }
        ).encode()
        plan = historical.preview(historical_source, "synthetic-history.json", {})
        batch = historical.commit(plan["preview_token"], str(uuid.uuid4()))
        assert accounting.summary("2026-01-01", "2026-01-31")["expense_fen"] == "4000"
        assert accounting.summary("2026-01-01", "2026-01-31")["net_fen"] == "6975"
        reports = Reports(accounting)
        assert reports.get("month", date(2026, 1, 3))["current"]["expense_fen"] == "4000"
        assert reports.get("day", date(2026, 1, 3))["current"]["expense_fen"] is None
        budgets = Budgets(accounting)
        assert budgets.get("2026-01")["items"] == []
        budgets.save("2026-01", expense_category, "5000", 0, str(uuid.uuid4()))
        assert budgets.get("2026-01")["items"][0]["remaining_fen"] == "1000"
        payload = store.backup()
        inspect_backup(payload)
        destination = store.restore(payload)
        restored = LedgerStore(destination)
        assert restored.metadata() == store.metadata(), "Restore mismatch"
        assert (
            Accounting(restored.engine).summary("2026-01-01", "2026-01-31")["expense_fen"] == "4000"
        )
        assert HistoryImports(Accounting(restored.engine)).detail(batch["id"])["rows"][0][
            "source_refs"
        ] == ["synthetic-source.png"]
        assert Accounting(restored.engine).accounts() == accounting.accounts()
        assert (
            Budgets(Accounting(restored.engine)).get("2026-01")["items"][0]["limit_fen"] == "5000"
        )
        restored.close()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        app = create_app(store, origin)
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="critical", ws="none", lifespan="off")
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert worker.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            body = json.dumps({"token": app.state.session.bootstrap}).encode()
            request = urllib.request.Request(
                origin + "/api/v1/session/bootstrap",
                data=body,
                headers={"Origin": origin, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                cookie = response.headers["Set-Cookie"].split(";")[0]
            request = urllib.request.Request(origin + "/api/v1/ledger", headers={"Cookie": cookie})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert json.load(response)["name"] == "Synthetic acceptance ledger"
            lock = FileLock(directory / "probe.lock")
            with lock:
                try:
                    FileLock(directory / "probe.lock").acquire(timeout=0)
                    raise AssertionError("Single-instance lock failed")
                except Timeout:
                    pass
        finally:
            server.should_exit = True
            worker.join(10)
            assert not worker.is_alive(), "Shutdown failed"
            sock.close()
            store.close()
    print("PASS: loopback/session/SQLite/WAL backup/restore/Chinese path/lock/shutdown")
