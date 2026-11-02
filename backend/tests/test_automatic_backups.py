"""Synthetic backup publication, retention and recovery fault injection."""

import io
import json
import threading
import time
import zipfile
from datetime import datetime, timedelta

import pytest
from pjz.automatic_backups import AutomaticBackups
from pjz.storage import DataError, LedgerStore, inspect_backup, write_verified_backup
from test_foundation import authenticate
from test_foundation import context as context


@pytest.fixture
def managed(tmp_path):
    store = LedgerStore(tmp_path / "合成账本")
    now = [datetime(2026, 1, 1, 12)]
    manager = AutomaticBackups(store, lambda: now[0], interval=0.02)
    yield store, manager, now
    manager.stop()
    store.close()


def rename(store):
    metadata = store.metadata()
    store.rename("Synthetic revision", metadata["revision"])


def test_daily_refresh_restart_and_no_change_next_day(managed):
    store, manager, now = managed
    assert manager.status()["pending"]
    manager.check()
    first = manager.status()
    assert not first["pending"] and len(first["files"]) == 1
    payload = manager.download("2026-01-01")
    now[0] += timedelta(days=1)
    manager.check()
    assert manager.download("2026-01-01") == payload
    assert len(manager.status()["files"]) == 1
    rename(store)
    manager.check()
    assert [f["id"] for f in manager.status()["files"]] == ["2026-01-02", "2026-01-01"]
    rename(store)
    manager.check()
    assert manager.status()["last_revision"] == store.metadata()["revision"]
    assert len(manager.status()["files"]) == 2
    restarted = AutomaticBackups(store, lambda: now[0])
    assert restarted.status() == manager.status()
    restored = LedgerStore(store.restore(manager.download("2026-01-02")))
    try:
        assert restored.metadata() == store.metadata()
    finally:
        restored.close()


def test_retention_does_not_delete_manual_safety_or_unknown_files(managed):
    store, manager, now = managed
    manager.check()
    manual = store.directory / "backups" / "manual.pjzbackup"
    manual.write_bytes(store.backup())
    upgrade = store.directory / "backups" / "before-v9-synthetic.pjzbackup"
    upgrade.write_bytes(store.backup())
    unknown = manager.directory / "daily-not-a-date.pjzbackup"
    unknown.write_bytes(b"preserve")
    for _ in range(15):
        now[0] += timedelta(days=1)
        rename(store)
        manager.check()
    files = manager.status()["files"]
    assert len(files) == 14
    assert files[-1]["id"] == "2026-01-03"
    assert manual.exists() and upgrade.exists() and unknown.read_bytes() == b"preserve"
    assert not (manager.directory / "daily-2026-01-01.pjzbackup").exists()


@pytest.mark.parametrize("stage", ["snapshot", "validate", "replace", "fsync"])
def test_failure_preserves_previous_daily_and_retry(managed, monkeypatch, stage):
    store, manager, _ = managed
    manager.check()
    before = manager.download("2026-01-01")
    rename(store)
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise OSError("synthetic disk failure")

        if stage == "snapshot":
            patch.setattr(store, "backup", fail)
        elif stage == "validate":
            patch.setattr("pjz.automatic_backups.inspect_backup", fail)
        else:
            patch.setattr("pjz.storage.os." + stage, fail)
        manager.check()
        assert manager.error == "AUTO_BACKUP_FAILED"
        assert manager.status()["pending"]
        assert (manager.directory / "daily-2026-01-01.pjzbackup").read_bytes() == before
        assert not list(manager.directory.glob(".pending-*"))
    manager.check()
    assert manager.error is None and not manager.status()["pending"]


def test_invalid_payload_cannot_replace_valid_file(managed):
    _, manager, _ = managed
    manager.check()
    path = manager.directory / "daily-2026-01-01.pjzbackup"
    before = path.read_bytes()
    with pytest.raises(DataError):
        write_verified_backup(path, b"corrupt")
    assert path.read_bytes() == before


def test_corrupt_current_is_preserved_and_retry_creates_verified_replacement(managed):
    _, manager, _ = managed
    manager.check()
    path = manager.directory / "daily-2026-01-01.pjzbackup"
    path.write_bytes(b"damaged synthetic bytes")
    assert manager.status()["invalid_count"] == 1
    assert manager.status()["pending"]
    manager.check(force=True)
    assert not manager.status()["pending"]
    assert [p.read_bytes() for p in manager.directory.glob("damaged-*")] == [
        b"damaged synthetic bytes"
    ]
    inspect_backup(manager.download("2026-01-01"))


def test_rollback_clock_never_prunes_latest_revision(managed):
    store, manager, now = managed
    manager.check()
    now[0] -= timedelta(days=1)
    rename(store)
    manager.check()
    assert manager.status()["files"][0]["id"] == "2025-12-31"
    assert not manager.status()["pending"]


def test_live_worker_and_final_shutdown_backup(managed):
    store, manager, _ = managed
    manager.start()
    try:
        deadline = time.monotonic() + 5
        while manager.status()["pending"] and time.monotonic() < deadline:
            time.sleep(0.01)
        rename(store)
        deadline = time.monotonic() + 5
        while manager.status()["pending"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not manager.status()["pending"]
        rename(store)
    finally:
        manager.stop()
    assert not manager.status()["pending"]
    assert not manager.worker.is_alive()


def test_snapshot_metadata_stays_consistent_with_concurrent_commit(managed, monkeypatch):
    store, _, _ = managed
    from pjz.storage import validate_database

    revision = store.metadata()["revision"]
    committed = threading.Event()

    def validate_and_commit(path):
        validate_database(path)
        rename(store)
        committed.set()

    monkeypatch.setattr("pjz.storage.validate_database", validate_and_commit)
    payload = store.backup()
    assert committed.is_set() and store.metadata()["revision"] == revision + 1
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        manifest = json.loads(package.read("manifest.json"))
    assert manifest["ledger_revision"] == revision
    monkeypatch.setattr("pjz.storage.validate_database", validate_database)
    inspect_backup(payload)


def test_restore_safety_failure_and_staged_failure_preserve_original(managed, monkeypatch):
    store, _, _ = managed
    payload = store.backup()
    rename(store)
    before = store.metadata()
    with monkeypatch.context() as patch:
        patch.setattr("pjz.storage.os.replace", lambda *a: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            store.restore(payload)
    assert store.metadata() == before
    assert not list(store.directory.parent.glob("restored-*"))
    with monkeypatch.context() as patch:
        original = LedgerStore.__init__

        def fail_staged(self, directory):
            if directory.name == "restored":
                raise DataError("synthetic recovery failure")
            original(self, directory)

        patch.setattr(LedgerStore, "__init__", fail_staged)
        with pytest.raises(DataError):
            store.restore(payload)
    assert store.metadata() == before
    assert not list(store.directory.parent.glob("restored-*"))
    safety = next((store.directory / "backups").glob("before-restore-*.pjzbackup"))
    inspect_backup(safety.read_bytes())


def test_backup_api_is_authenticated_and_has_no_arbitrary_path(context):
    store, app, client = context
    assert client.get("/api/v1/automatic-backups").status_code == 401
    headers = authenticate(app, client)
    assert client.post("/api/v1/automatic-backups/retry", json={}).status_code == 403
    result = client.post("/api/v1/automatic-backups/retry", json={}, headers=headers)
    assert result.status_code == 200 and result.json()["error"] is None
    identifier = result.json()["files"][0]["id"]
    response = client.get("/api/v1/automatic-backups/" + identifier)
    inspect_backup(response.content)
    assert client.get("/api/v1/automatic-backups/ledger.sqlite3").status_code == 400
    assert (
        client.get(
            "/api/v1/automatic-backups/" + identifier, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/automatic-backups", headers={"Host": "evil.example"}).status_code == 403
    )


def test_rotation_failure_preserves_verified_new_backup(managed, monkeypatch):
    store, manager, now = managed
    manager.retention = 1
    manager.check()
    now[0] += timedelta(days=1)
    rename(store)
    from pathlib import Path

    original = Path.unlink

    def fail_old(path, *args, **kwargs):
        if path.name == "daily-2026-01-01.pjzbackup":
            raise PermissionError("synthetic")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_old)
        manager.check()
        assert manager.error == "AUTO_BACKUP_FAILED"
        assert len(manager.status()["files"]) == 2
        assert not manager.status()["pending"]
    manager.check(force=True)
    assert manager.error is None and len(manager.status()["files"]) == 1


def test_link_and_foreign_ledger_are_not_downloadable(managed, tmp_path, monkeypatch):
    store, manager, _ = managed
    manager.check()
    other = LedgerStore(tmp_path / "other-synthetic")
    try:
        (manager.directory / "daily-2025-12-01.pjzbackup").write_bytes(other.backup())
    finally:
        other.close()
    assert manager.status()["invalid_count"] == 1
    with pytest.raises(DataError, match="BACKUP_NOT_FOUND"):
        manager.download("2025-12-01")
    from pathlib import Path

    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == manager.directory or original(path)
    )
    manager.check(force=True)
    assert manager.error == "AUTO_BACKUP_FAILED"
    with pytest.raises(DataError, match="BACKUP_UNSAFE_PATH"):
        manager.download("2026-01-01")


def test_automatic_snapshot_restores_cash_positions_and_returns(managed):
    store, manager, _ = managed
    from pjz.accounting import Accounting
    from pjz.investments import Investments
    from sqlalchemy import text

    accounting = Accounting(store.engine)
    # Reuse API validators and synthetic fixtures, including WAL-committed investment writes.
    from fastapi.testclient import TestClient
    from pjz.api import create_app
    from test_daily_ledger import account
    from test_investments import instrument, price, trade

    app = create_app(store, "http://127.0.0.1:8765")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        headers = authenticate(app, client)
        ledger = store, client, headers
        cash = account(ledger, "Synthetic auto cash", "1000000", "securities")
        stock = instrument(ledger)
        assert trade(ledger, cash, stock).status_code == 200
        assert price(ledger, stock).status_code == 200
    expected = Investments(accounting).page()
    manager.check(force=True)
    recovered = LedgerStore(store.restore(manager.download("2026-01-01")))
    try:
        assert Investments(Accounting(recovered.engine)).page() == expected
        with recovered.engine.connect() as connection:
            assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
    finally:
        recovered.close()
