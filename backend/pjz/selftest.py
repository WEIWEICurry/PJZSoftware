"""Packaged executable acceptance probe, using only temporary synthetic data."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from pjz.accounting import Accounting
from pjz.api import create_app
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
        payload = store.backup()
        inspect_backup(payload)
        destination = store.restore(payload)
        restored = LedgerStore(destination)
        assert restored.metadata() == store.metadata(), "Restore mismatch"
        assert (
            Accounting(restored.engine).summary("2026-01-01", "2026-01-31")["expense_fen"] == "3025"
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
