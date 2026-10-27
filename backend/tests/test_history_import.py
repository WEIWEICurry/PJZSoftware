"""Historical migration tests use synthetic inputs, never local staging files."""

import hashlib
import io
import json
import sqlite3
import time
import uuid
import zipfile
from contextlib import closing

import pytest
from pjz.accounting import Accounting
from pjz.domain import RuleError
from pjz.history import HistoryImports
from pjz.history_domain import MAX_SOURCE, parse_source
from pjz.storage import DataError, LedgerStore, inspect_backup, validate_database
from sqlalchemy import text
from test_daily_ledger import account, category, event, send, summary
from test_daily_ledger import ledger as ledger
from test_simple_loans import legacy_v2


def source(categories=None, end="2026-01-20", direction="expense"):
    return {
        "schema_version": 1,
        "currency": "CNY",
        "amount_unit": "fen",
        "record_type": "monthly_category_summary",
        "source_app": "Synthetic source",
        "periods": [
            {
                "start_date": "2026-01-01",
                "end_date": end,
                "direction": direction,
                "displayed_total_fen": sum((categories or {"餐饮": 15000}).values()),
                "source_images": ["synthetic-source.png"],
                "categories": [
                    {"category": name, "amount_fen": amount}
                    for name, amount in (categories or {"餐饮": 15000}).items()
                ],
            }
        ],
    }


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


def preview(ledger, value, mapping=None, filename="synthetic.json"):
    raw = value if isinstance(value, bytes) else encoded(value)
    return ledger[1].post(
        "/api/v1/history/preview",
        files={"file": (filename, raw, "application/json")},
        data={"mapping": json.dumps(mapping or {})},
        headers=ledger[2],
    )


def commit(ledger, plan, key=None):
    return send(
        ledger,
        "/history/commit",
        {"preview_token": plan["preview_token"], "acknowledge_coverage": True},
        key=key,
    )


def seeded_details(ledger):
    bank = account(ledger, "Synthetic bank")
    cash = account(ledger, "Synthetic cash", "0", "cash")
    original = event(ledger, bank, "10000")
    event(
        ledger,
        bank,
        "2000",
        "refund",
        original_event_id=original["id"],
        effective_date="2026-01-12",
    )
    event(
        ledger,
        bank,
        "1000",
        "transfer",
        target_account_id=cash,
        fee_fen="100",
        category_id=category(ledger, "手续费"),
        effective_date="2026-01-12",
    )
    event(ledger, bank, "700", category_id=category(ledger, "其他支出"))
    event(ledger, bank, "300", effective_date="2026-01-21")
    event(ledger, bank, "50000", "income")
    return bank


def test_preview_import_coverage_refund_fee_and_future_detail(ledger):
    store, client, _ = ledger
    bank = seeded_details(ledger)
    before = summary(ledger)
    revision = store.metadata()
    plan = preview(ledger, source({"餐饮": 15000, "手续费": 200})).json()
    assert plan["can_confirm"]
    assert [r["report_delta_fen"] for r in plan["rows"]] == ["7000", "100"]
    assert [(r["detail_count"], r["detail_fen"]) for r in plan["rows"]] == [(2, "8000"), (1, "100")]
    assert store.metadata() == revision
    assert client.get("/api/v1/history/batches").json() == []
    result = commit(ledger, plan)
    assert result.status_code == 200, result.text
    after = summary(ledger)
    assert after["income_fen"] == "50000" and after["expense_fen"] == "16200"
    assert after["assets_fen"] == before["assets_fen"] == "140900"
    assert after["covered_detail_count"] == "3"
    event(ledger, bank, "100", effective_date="2026-01-15")
    assert summary(ledger)["expense_fen"] == "16200"
    assert summary(ledger)["assets_fen"] == "140800"
    rows = client.get("/api/v1/events", params={"start": "2026-01-01", "end": "2026-01-31"}).json()[
        "items"
    ]
    assert sum(r["covered_by_history"] for r in rows) == 4
    with pytest.raises(RuleError, match="HISTORY_DAILY_UNAVAILABLE"):
        Accounting(store.engine).summary("2026-01-01", "2026-01-10")
    detail = client.get("/api/v1/history/batches/" + result.json()["id"]).json()
    assert detail["rows"][0]["source_refs"] == ["synthetic-source.png"]


def test_file_rename_reorder_and_mapping_conflicts(ledger):
    value = source({"餐饮": 15000, "日用": 900})
    plan = preview(ledger, value).json()
    assert commit(ledger, plan).status_code == 200
    assert {
        r["status"] for r in preview(ledger, value, filename="renamed.json").json()["rows"]
    } == {"duplicate"}
    value["periods"][0]["categories"].reverse()
    reordered = json.dumps(value, indent=4).encode()
    repeated = preview(ledger, reordered).json()
    assert repeated["canonical_hash"] == plan["canonical_hash"]
    assert not repeated["can_confirm"]
    assert commit(ledger, repeated).status_code == 422
    conflict = preview(ledger, source({"餐饮": 14000})).json()
    assert conflict["rows"][0]["status"] == "conflict"
    unmapped = preview(ledger, source({"Synthetic custom": 200})).json()
    assert unmapped["rows"][0]["status"] == "unmapped"
    mapped = preview(
        ledger,
        source({"Synthetic custom": 200}),
        {"expense:Synthetic custom": category(ledger, "其他支出")},
    ).json()
    assert mapped["can_confirm"]
    assert commit(ledger, mapped).status_code == 200
    wrong = preview(
        ledger,
        source({"Synthetic other": 100}),
        {"expense:Synthetic other": category(ledger, "工资")},
    )
    assert wrong.status_code == 422
    # Mapping two source classes onto an overlapping destination must not silently add them.
    clash = preview(
        ledger,
        source({"Synthetic one": 1, "Synthetic two": 2}),
        {
            "expense:Synthetic one": category(ledger, "交通"),
            "expense:Synthetic two": category(ledger, "交通"),
        },
    ).json()
    assert {r["status"] for r in clash["rows"]} == {"conflict"}
    assert commit(ledger, clash).status_code == 422


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda v: v.update(currency="USD"), "HISTORY_UNSUPPORTED_FORMAT"),
        (lambda v: v.update(amount_unit="yuan"), "HISTORY_UNSUPPORTED_FORMAT"),
        (lambda v: v.update(schema_version=True), "HISTORY_UNSUPPORTED_FORMAT"),
        (lambda v: v["periods"][0].update(displayed_total_fen=1), "HISTORY_TOTAL_MISMATCH"),
        (lambda v: v["periods"][0].update(end_date="2026-02-01"), "HISTORY_INVALID_PERIOD"),
        (lambda v: v["periods"][0].update(start_date="2026-01-21"), "HISTORY_INVALID_PERIOD"),
        (
            lambda v: v["periods"][0].update(start_date="2999-01-01", end_date="2999-01-02"),
            "HISTORY_INVALID_PERIOD",
        ),
        (
            lambda v: v["periods"][0]["categories"][0].update(amount_fen=-1),
            "HISTORY_INVALID_AMOUNT",
        ),
        (
            lambda v: v["periods"][0]["categories"][0].update(amount_fen=1.0),
            "HISTORY_INVALID_AMOUNT",
        ),
        (
            lambda v: v["periods"][0]["categories"].append(v["periods"][0]["categories"][0]),
            "HISTORY_SOURCE_OVERLAP",
        ),
    ],
)
def test_invalid_source_no_writes(ledger, mutation, code):
    value = source()
    mutation(value)
    before = ledger[0].metadata()
    response = preview(ledger, value)
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert ledger[0].metadata() == before


def test_json_bom_duplicate_keys_size_zero_and_staged_adapter(ledger):
    value = source({"餐饮": 0})
    value["record_type"] = "monthly_category_expense_summary"
    value["periods"][0].pop("direction")
    assert preview(ledger, b"\xef\xbb\xbf" + encoded(value)).json()["can_confirm"]
    assert preview(ledger, b'{"schema_version":1,"schema_version":1}').status_code == 422
    assert (
        preview(ledger, b" " * (MAX_SOURCE + 1)).json()["error"]["code"] == "HISTORY_FILE_TOO_LARGE"
    )
    with pytest.raises(RuleError):
        parse_source(b"[1,2]")
    blocked = preview(ledger, source({"学习": 10}), {"expense:学习": ""}).json()
    assert not blocked["can_confirm"]
    assert commit(ledger, blocked).status_code == 422


def test_version_expiry_ack_retry_and_atomic_rollback(ledger, monkeypatch):
    store, client, _ = ledger
    service = HistoryImports(Accounting(store.engine))
    plan = service.preview(encoded(source()), "synthetic.json", {})
    key = str(uuid.uuid4())
    result = service.commit(plan["preview_token"], key)
    service.previews.clear()
    assert service.commit(plan["preview_token"], key) == result
    assert len(client.get("/api/v1/history/batches").json()) == 1
    plan = service.preview(encoded(source({"日用": 10})), "other.json", {})
    account(ledger, "Synthetic concurrent")
    with pytest.raises(RuleError, match="REVISION_CONFLICT"):
        service.commit(plan["preview_token"], str(uuid.uuid4()))
    plan = service.preview(encoded(source({"日用": 10})), "other.json", {})
    service.previews[plan["preview_token"]]["expires"] = time.monotonic() - 1
    with pytest.raises(RuleError, match="PREVIEW_EXPIRED"):
        service.commit(plan["preview_token"], str(uuid.uuid4()))
    plan = service.preview(encoded(source({"日用": 10})), "other.json", {})

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic after-insert failure")

    before = store.metadata()
    monkeypatch.setattr(service.accounting, "rebuild", fail)
    with pytest.raises(RuntimeError):
        service.commit(plan["preview_token"], str(uuid.uuid4()))
    assert store.metadata() == before
    assert len(client.get("/api/v1/history/batches").json()) == 1
    api_plan = preview(ledger, source({"日用": 10})).json()
    assert (
        send(
            ledger,
            "/history/commit",
            {"preview_token": api_plan["preview_token"], "acknowledge_coverage": False},
        ).status_code
        == 422
    )


def test_withdraw_preview_retry_reimport_and_income_direction(ledger):
    seeded_details(ledger)
    imported = commit(ledger, preview(ledger, source()).json()).json()
    before = summary(ledger)
    plan = send(ledger, "/history/batches/" + imported["id"] + "/withdraw-preview", {}).json()
    assert plan["rows"][0]["detail_fen"] == "8000"
    assert plan["rows"][0]["report_delta_fen"] == "-7000"
    assert summary(ledger) == before
    key = str(uuid.uuid4())
    assert commit(ledger, plan, key).json()["status"] == "withdrawn"
    assert commit(ledger, plan, key).json()["status"] == "withdrawn"
    assert summary(ledger)["expense_fen"] == "9100"
    assert summary(ledger)["assets_fen"] == before["assets_fen"]
    assert commit(ledger, preview(ledger, source()).json()).status_code == 200
    income = preview(ledger, source({"工资": 60000}, direction="income")).json()
    assert income["can_confirm"]
    assert commit(ledger, income).status_code == 200
    assert summary(ledger)["income_fen"] == "60000"


def test_backup_restore_sources_and_tampered_rows_rejected(ledger, tmp_path):
    store, client, _ = ledger
    result = commit(ledger, preview(ledger, source()).json()).json()
    original = client.get("/api/v1/history/batches/" + result["id"]).json()
    snapshot = inspect_backup(store.backup())
    restored_path = store.restore(store.backup())
    restored = LedgerStore(restored_path)
    try:
        assert (
            HistoryImports(Accounting(restored.engine)).detail(result["id"])["file_hash"]
            == original["file_hash"]
        )
        assert (
            Accounting(restored.engine).summary("2026-01-01", "2026-01-31")["expense_fen"]
            == "15000"
        )
        with restored.engine.connect() as c:
            raw = c.execute(text("SELECT source_blob FROM import_batches")).scalar_one()
            assert raw == encoded(source())
    finally:
        restored.close()
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(snapshot)
    with closing(sqlite3.connect(damaged)) as c:
        c.execute("UPDATE historical_summaries SET amount_fen=amount_fen+1")
        c.commit()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(DataError):
        validate_database(damaged)
    # Recompute the package checksum: business validation must still reject tampering.
    package = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(store.backup())) as z:
        manifest = json.loads(z.read("manifest.json"))
    payload = damaged.read_bytes()
    manifest["files"]["ledger.sqlite3"] = {
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("ledger.sqlite3", payload)
    with pytest.raises(DataError):
        inspect_backup(package.getvalue())


def test_v3_to_v4_migration_and_failure_backup(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    path = tmp_path / "legacy"
    database = legacy_v2(path)
    engine = create_engine("sqlite:///" + database.as_posix())
    config = Config()
    config.set_main_option("script_location", "backend/pjz/migrations")
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")
        c.commit()
        c.exec_driver_sql("BEGIN IMMEDIATE")
        config.attributes["connection"] = c
        command.upgrade(config, "0003")
        c.commit()
    engine.dispose()
    original = command.upgrade

    def fail(config, revision):
        original(config, revision)
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        LedgerStore(path)
    with sqlite3.connect(database) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert not c.execute(
            "SELECT name FROM sqlite_master WHERE name='import_batches'"
        ).fetchall()
    assert list((path / "backups").glob("before-v4-*"))
    monkeypatch.setattr(command, "upgrade", original)
    store = LedgerStore(path)
    try:
        assert Accounting(store.engine).accounts()[0]["balance_fen"] == "70000"
        assert HistoryImports(Accounting(store.engine)).batches() == []
        validate_database(store.path)
    finally:
        store.close()
