"""Only synthetic ledgers: deletion graph, backup safety, retry and note frequency."""

import io
import time
import uuid
import zipfile

import pytest
from pjz.account_deletion import AccountDeletion
from pjz.accounting import Accounting
from pjz.domain import RuleError
from pjz.storage import LedgerStore
from sqlalchemy import text
from test_daily_ledger import account, category, event, send, summary
from test_daily_ledger import ledger as ledger


def archive(ledger, identifier, name):
    response = send(
        ledger,
        f"/accounts/{identifier}",
        {
            "name": name,
            "revision": 1,
            "archived": True,
        },
        "PATCH",
    )
    assert response.status_code == 200, response.text


def preview(ledger, identifier):
    response = send(ledger, f"/accounts/{identifier}/delete-preview", {})
    assert response.status_code == 200, response.text
    return response.json()


def commit(ledger, identifier, plan, name, key=None):
    return send(
        ledger,
        f"/accounts/{identifier}/delete",
        {
            "preview_token": plan["preview_token"],
            "confirm_name": name,
        },
        key=key,
    )


def test_empty_delete_preview_no_write_retry_and_old_request_purged(ledger):
    store, client, _ = ledger
    original_key = str(uuid.uuid4())
    payload = {
        "name": "Synthetic empty",
        "kind": "bank",
        "opening_date": "2026-01-01",
        "opening_fen": "0",
    }
    identifier = send(ledger, "/accounts", payload, key=original_key).json()["id"]
    archive(ledger, identifier, payload["name"])
    before = store.metadata()
    plan = preview(ledger, identifier)
    assert plan["can_delete"] and plan["event_count"] == 1
    assert store.metadata() == before
    assert len(client.get("/api/v1/accounts").json()) == 1
    assert not list((store.directory / "backups").glob("before-delete-*"))
    key = str(uuid.uuid4())
    response = commit(ledger, identifier, plan, payload["name"], key)
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/accounts").json() == []
    assert commit(ledger, identifier, plan, payload["name"], key).json() == response.json()
    assert len(list((store.directory / "backups").glob("before-delete-*"))) == 1
    retry = send(ledger, "/accounts", payload, key=original_key)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "RESOURCE_DELETED"
    with store.engine.connect() as connection:
        audits = connection.execute(
            text("SELECT before_json,after_json FROM operation_revisions")
        ).fetchall()
        receipts = connection.execute(
            text("SELECT result_json FROM idempotency_records")
        ).fetchall()
    assert "Synthetic empty" not in str(audits) + str(receipts)


def linked_ledger(ledger, spending=False):
    original = account(ledger, "Synthetic old")
    bank = account(ledger, "Synthetic remaining", "0")
    expense = event(ledger, original, "10000", note="Synthetic private note")
    event(ledger, bank, "2000", "refund", original_event_id=expense["id"])
    event(ledger, original, "90000", "transfer", target_account_id=bank)
    if spending:
        event(ledger, bank, "1000")
    archive(ledger, original, "Synthetic old")
    return original, bank


def test_delete_shared_transfer_and_refund_restorable_backup(ledger):
    store, client, _ = ledger
    original, bank = linked_ledger(ledger)
    unrelated = account(ledger, "Synthetic unrelated", "0")
    event(ledger, unrelated, "5000", "income")
    before = Accounting(store.engine).events("2026-01-01", "2026-01-31")
    plan = preview(ledger, original)
    assert plan["event_count"] == 4
    assert plan["refund_count"] == plan["transfer_count"] == 1
    assert plan["other_accounts"] == [
        {
            "account_id": bank,
            "name": "Synthetic remaining",
            "before_fen": "92000",
            "after_fen": "0",
        }
    ]
    response = commit(ledger, original, plan, "Synthetic old")
    assert response.status_code == 200, response.text
    assert {item["id"] for item in client.get("/api/v1/accounts").json()} == {bank, unrelated}
    assert summary(ledger)["assets_fen"] == "5000"
    assert summary(ledger)["expense_fen"] == "0"
    assert summary(ledger)["income_fen"] == "5000"
    with zipfile.ZipFile(io.BytesIO(store.backup())) as current_backup:
        assert b"Synthetic private note" not in current_backup.read("ledger.sqlite3")
        assert b"Synthetic old" not in current_backup.read("ledger.sqlite3")
    assert (
        client.get(f"/api/v1/categories/{category(ledger, '餐饮')}/note-suggestions").json() == []
    )
    from pathlib import Path

    backup = Path(response.json()["backup_path"])
    restored = LedgerStore(store.restore(backup.read_bytes()))
    service = Accounting(restored.engine)
    assert service.events("2026-01-01", "2026-01-31") == before
    assert any(item["name"] == "Synthetic old" for item in service.accounts())
    restored.close()


def test_delete_blocked_by_remaining_historical_balance(ledger):
    store, _, _ = ledger
    original, _ = linked_ledger(ledger, spending=True)
    before = store.metadata()
    plan = preview(ledger, original)
    assert not plan["can_delete"]
    assert plan["reason"] == "INSUFFICIENT_BALANCE"
    assert plan["other_accounts"][0]["after_fen"] == "-1000"
    response = commit(ledger, original, plan, "Synthetic old")
    assert response.status_code == 422
    assert store.metadata() == before
    assert len(Accounting(store.engine).accounts()) == 2
    assert not list((store.directory / "backups").glob("before-delete-*"))


def test_delete_confirmation_revision_expiration_and_archive_guard(ledger):
    store, _, _ = ledger
    identifier = account(ledger, "Synthetic")
    assert send(ledger, f"/accounts/{identifier}/delete-preview", {}).status_code == 422
    # Archive a zero account for confirmation checks.
    identifier = account(ledger, "Synthetic zero", "0")
    archive(ledger, identifier, "Synthetic zero")
    plan = preview(ledger, identifier)
    assert commit(ledger, identifier, plan, "wrong name").status_code == 422
    account(ledger, "Synthetic unrelated", "0")
    assert commit(ledger, identifier, plan, "Synthetic zero").status_code == 409
    deletion = AccountDeletion(store)
    plan = deletion.preview(identifier)
    deletion.previews[plan["preview_token"]] = (
        identifier,
        store.metadata()["revision"],
        time.monotonic() - 1,
    )
    with pytest.raises(RuleError, match="PREVIEW_EXPIRED"):
        deletion.commit(
            identifier,
            {"preview_token": plan["preview_token"], "confirm_name": "Synthetic zero"},
            str(uuid.uuid4()),
        )


def test_backup_failure_and_post_delete_failure_rollback(ledger, monkeypatch):
    store, _, _ = ledger
    identifier = account(ledger, "Synthetic zero", "0")
    archive(ledger, identifier, "Synthetic zero")
    deletion = AccountDeletion(store)
    plan = deletion.preview(identifier)
    before = store.metadata()
    original_backup = store.backup

    def fail_backup():
        raise OSError("Synthetic disk failure")

    monkeypatch.setattr(store, "backup", fail_backup)
    payload = {"preview_token": plan["preview_token"], "confirm_name": "Synthetic zero"}
    with pytest.raises(RuleError, match="BACKUP_FAILED"):
        deletion.commit(identifier, payload, str(uuid.uuid4()))
    assert store.metadata() == before
    monkeypatch.setattr(store, "backup", original_backup)
    remove = deletion.remove
    calls = 0

    def fail_after_removal(connection, planned):
        nonlocal calls
        calls += 1
        remove(connection, planned)
        if calls == 2:
            raise RuleError("Synthetic rollback")

    monkeypatch.setattr(deletion, "remove", fail_after_removal)
    with pytest.raises(RuleError, match="Synthetic rollback"):
        deletion.commit(identifier, payload, str(uuid.uuid4()))
    assert store.metadata() == before
    assert len(Accounting(store.engine).accounts()) == 1
    assert len(list((store.directory / "backups").glob("before-delete-*"))) == 1
    assert not list((store.directory / "backups").glob("*.tmp"))


def test_note_frequency_category_whitespace_void_edit_and_reopen(ledger):
    store, client, _ = ledger
    bank = account(ledger, "Synthetic")
    one = event(ledger, bank, "1", note="  Synthetic lunch  ")
    event(ledger, bank, "1", note="Synthetic lunch")
    event(ledger, bank, "1", note="Synthetic lunch\u3000")
    dinner = event(ledger, bank, "1", note="Synthetic dinner")
    event(ledger, bank, "1", note="Synthetic dinner")
    event(ledger, bank, "1", note=" \u3000 ")
    event(ledger, bank, "1", "income", note="Synthetic income only")
    identifier = category(ledger, "餐饮")
    path = f"/api/v1/categories/{identifier}/note-suggestions"
    assert client.get(path).json() == [
        {"note": "Synthetic lunch", "count": 3},
        {"note": "Synthetic dinner", "count": 2},
    ]
    assert send(ledger, f"/events/{dinner['id']}/void", {"revision": 1}).status_code == 200
    body = {key: value for key, value in one.items() if key not in ("id", "status")}
    body["note"] = "Synthetic edited"
    assert send(ledger, f"/events/{one['id']}", body, "PUT").status_code == 200
    expected = client.get(path).json()
    assert expected[0] == {"note": "Synthetic lunch", "count": 2}
    assert len(expected) == 3
    reopened = LedgerStore(store.directory)
    assert Accounting(reopened.engine).note_suggestions(identifier) == expected
    reopened.close()
    for index in range(6):
        event(ledger, bank, "1", note=f"Synthetic extra {index}")
    result = client.get(path).json()
    assert len(result) == 5
    assert result[1]["note"] == "Synthetic extra 5"
    assert not any(item["note"] == "Synthetic income only" for item in result)
