import hashlib
import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pjz.api import create_app
from pjz.storage import DataError, LedgerStore, inspect_backup
from sqlalchemy import text

ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def context(tmp_path):
    store = LedgerStore(tmp_path / "中文账本")
    app = create_app(store, ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        yield store, app, client
    store.close()


def authenticate(app, client):
    response = client.post(
        "/api/v1/session/bootstrap",
        json={"token": app.state.session.bootstrap},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_authentication_host_origin_and_csrf(context):
    store, app, client = context
    assert client.get("/api/v1/ledger").status_code == 401
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
    token = app.state.session.bootstrap
    assert client.post("/api/v1/session/bootstrap", json={"token": token}).status_code == 403
    assert (
        client.post(
            "/api/v1/session/bootstrap",
            json={"token": token},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    headers = authenticate(app, client)
    assert (
        client.post(
            "/api/v1/session/bootstrap", json={"token": token}, headers={"Origin": ORIGIN}
        ).status_code
        == 401
    )
    assert (
        client.get("/api/v1/ledger", headers={"Origin": "https://evil.example"}).status_code == 403
    )
    assert client.post("/api/v1/backups", json={}, headers={"Origin": ORIGIN}).status_code == 403
    response = client.post("/api/v1/backups", json={}, headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_bootstrap_expiration_and_process_session_isolation(context):
    store, app, client = context
    app.state.session.expires = time.monotonic() - 1
    assert (
        client.post(
            "/api/v1/session/bootstrap",
            json={"token": app.state.session.bootstrap},
            headers={"Origin": ORIGIN},
        ).status_code
        == 401
    )
    app.state.session.issue_bootstrap()
    authenticate(app, client)
    assert client.get("/api/v1/ledger").status_code == 200
    with TestClient(create_app(store, ORIGIN), base_url=ORIGIN) as other:
        other.cookies.update(client.cookies)
        assert other.get("/api/v1/ledger").status_code == 401


def test_persistence_revision_conflict_and_validation(context):
    store, app, client = context
    headers = authenticate(app, client)
    metadata = client.get("/api/v1/ledger").json()
    body = {"name": "Synthetic ledger", "revision": metadata["revision"]}
    assert client.put("/api/v1/ledger", json=body, headers=headers).status_code == 200
    assert client.put("/api/v1/ledger", json=body, headers=headers).status_code == 409
    for invalid in [" ", "", "x" * 61]:
        assert (
            client.put(
                "/api/v1/ledger", json={"name": invalid, "revision": 2}, headers=headers
            ).status_code
            == 422
        )
    response = client.put("/api/v1/ledger", json={"name": "x", "revision": 2.5}, headers=headers)
    assert response.status_code == 422
    # Validation errors must not echo arbitrary private inputs.
    assert "input" not in response.text
    reopened = LedgerStore(store.directory)
    assert reopened.metadata()["name"] == "Synthetic ledger"
    reopened.close()


def test_transaction_rollback(context):
    store, _, _ = context
    original = store.metadata()
    with pytest.raises(RuntimeError), store.engine.begin() as connection:
        connection.execute(text("UPDATE ledger SET name='must roll back'"))
        raise RuntimeError("synthetic failure")
    assert store.metadata() == original


def test_backup_includes_wal_and_restore_preserves_original(context):
    store, _, _ = context
    store.rename("Synthetic before backup", 1)
    payload = store.backup()
    store.rename("Synthetic current", 2)
    restored_dir = store.restore(payload)
    restored = LedgerStore(restored_dir)
    assert restored.metadata()["name"] == "Synthetic before backup"
    assert restored.metadata()["revision"] == 2
    assert store.metadata()["name"] == "Synthetic current"
    safety = list((store.directory / "backups").glob("*.pjzbackup"))
    assert len(safety) == 1
    inspect_backup(safety[0].read_bytes())
    restored.close()


def repack(payload, mutate):
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    mutate(entries)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        for name, data in entries.items():
            package.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize("attack", ["garbage", "checksum", "traversal", "newer", "duplicate"])
def test_invalid_backup_rejected_without_data_loss(context, attack):
    store, _, _ = context
    original = store.metadata()
    payload = store.backup()
    if attack == "garbage":
        payload = b"not a backup"
    elif attack == "checksum":
        payload = repack(payload, lambda files: files.update({"ledger.sqlite3": b"bad"}))
    elif attack == "traversal":
        payload = repack(payload, lambda files: files.update({"../escape": b"bad"}))
    elif attack == "newer":

        def mutate(files):
            manifest = json.loads(files["manifest.json"])
            manifest["schema_version"] = 999
            files["manifest.json"] = json.dumps(manifest).encode()

        payload = repack(payload, mutate)
    elif attack == "duplicate":
        output = io.BytesIO(payload)
        with zipfile.ZipFile(output, "a") as package:
            with pytest.warns(UserWarning):
                package.writestr("ledger.sqlite3", b"bad")
        payload = output.getvalue()
    with pytest.raises(DataError):
        store.restore(payload)
    assert store.metadata() == original
    assert not list(store.directory.parent.glob("restored-*"))


def test_unsupported_live_schema_never_recreated(tmp_path):
    directory = tmp_path / "future"
    directory.mkdir()
    path = directory / "ledger.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(DataError, match="UNSUPPORTED_SCHEMA"):
        LedgerStore(directory)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_restore_preview_stale_and_single_use(context):
    store, app, client = context
    headers = authenticate(app, client)
    payload = store.backup()

    def preview():
        return client.post(
            "/api/v1/restores/preview", files={"file": ("test.pjzbackup", payload)}, headers=headers
        ).json()["preview_token"]

    token = preview()
    store.rename("Synthetic changed", 1)
    assert (
        client.post(
            "/api/v1/restores/commit", json={"preview_token": token}, headers=headers
        ).status_code
        == 409
    )
    token = preview()
    response = client.post(
        "/api/v1/restores/commit", json={"preview_token": token}, headers=headers
    )
    assert response.status_code == 200
    assert Path(response.json()["directory"]).is_dir()
    assert (
        client.post(
            "/api/v1/restores/commit", json={"preview_token": token}, headers=headers
        ).status_code
        == 409
    )


def test_declared_and_streaming_body_limits(context):
    _, app, client = context
    headers = authenticate(app, client)
    assert (
        client.post(
            "/api/v1/backups",
            content=b"{}",
            headers={
                **headers,
                "Content-Type": "application/json",
                "Content-Length": "99999999",
            },
        ).status_code
        == 413
    )

    def oversized():
        for _ in range(9):
            yield b"x" * (1024 * 1024)

    assert (
        client.post(
            "/api/v1/backups",
            content=oversized(),
            headers={
                **headers,
                "Content-Type": "application/json",
            },
        ).status_code
        == 413
    )
