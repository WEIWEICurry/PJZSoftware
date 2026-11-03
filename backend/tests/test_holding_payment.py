"""Independent cash and merged moving-cost acceptance; synthetic records only."""

import uuid
from pathlib import Path

from pjz.accounting import Accounting
from pjz.storage import LedgerStore, inspect_backup
from test_daily_ledger import account, send
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, trade


def balances(ledger):
    return {a["id"]: a["balance_fen"] for a in ledger[1].get("/api/v1/accounts").json()}


def test_two_payments_one_holding_and_independent_sale_receipt(ledger):
    bank_a = account(ledger, "Synthetic bank A", "1000000")
    bank_b = account(ledger, "Synthetic bank B", "1000000")
    platform = account(ledger, "Synthetic Alipay", "0", "securities")
    receipt = account(ledger, "Synthetic receipt", "0")
    asset = instrument(ledger)
    assert trade(ledger, platform, asset, cash_account_id=bank_a).status_code == 200
    assert (
        trade(
            ledger,
            platform,
            asset,
            cash_account_id=bank_b,
            amount_fen="120000",
            effective_date="2026-01-11",
        ).status_code
        == 200
    )
    assert len(page(ledger)["positions"]) == 1
    result = trade(
        ledger,
        platform,
        asset,
        action="sell",
        quantity="150",
        amount_fen="180000",
        costs_fen="200",
        cash_account_id=receipt,
        effective_date="2026-01-12",
    )
    assert result.status_code == 200, result.text
    p = page(ledger)["positions"][0]
    assert (p["quantity"], p["cost_fen"], p["realized_fen"]) == ("50", "55250", "14050")
    b = balances(ledger)
    assert (b[bank_a], b[bank_b], b[receipt], b[platform]) == ("899500", "879500", "179800", "0")
    before = page(ledger)
    assert (
        trade(ledger, platform, asset, cash_account_id=receipt, amount_fen="99999999").status_code
        == 422
    )
    assert page(ledger) == before


def test_history_transfer_preview_backup_retry_and_stale(ledger):
    a = account(ledger, "Synthetic legacy A", "1000000")
    b = account(ledger, "Synthetic legacy B", "1000000")
    target = account(ledger, "Synthetic platform", "0", "securities")
    asset = instrument(ledger)
    assert (
        trade(
            ledger,
            a,
            asset,
            action="opening",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen="100500",
        ).status_code
        == 200
    )
    assert trade(ledger, b, asset, effective_date="2026-01-11").status_code == 200
    original = page(ledger)
    cash_before = balances(ledger)
    body = {"instrument_id": asset, "source_account_ids": [a, b], "target_account_id": target}
    preview = send(ledger, "/investments/holding-transfer/preview", body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["quantity"] == "200"
    assert page(ledger) == original
    key = str(uuid.uuid4())
    commit = {
        **body,
        "ledger_revision": preview.json()["ledger_revision"],
        "preview_token": preview.json()["preview_token"],
    }
    result = send(ledger, "/investments/holding-transfer/commit", commit, key=key)
    assert result.status_code == 200, result.text
    assert (
        send(ledger, "/investments/holding-transfer/commit", commit, key=key).json()
        == result.json()
    )
    assert balances(ledger) == cash_before
    after = page(ledger)
    assert len(after["positions"]) == 1
    assert after["positions"][0]["cost_fen"] == "201000"
    assert {t["cash_account_id"] for t in after["trades"]} == {None, b}
    assert {t["id"] for t in after["trades"]} == {t["id"] for t in original["trades"]}
    backup = Path(result.json()["backup_path"]).read_bytes()
    inspect_backup(backup)
    restored = LedgerStore(ledger[0].restore(backup))
    try:
        from pjz.investments import Investments

        restored_page = Investments(Accounting(restored.engine)).page()
        assert restored_page["positions"] == original["positions"]
    finally:
        restored.close()
    assert send(ledger, "/investments/holding-transfer/commit", commit).status_code == 409


def test_multiple_openings_rejected_atomically(ledger):
    a = account(ledger, "Synthetic A")
    b = account(ledger, "Synthetic B")
    target = account(ledger, "Synthetic target", "0", "securities")
    asset = instrument(ledger)
    for account_id in (a, b):
        assert (
            trade(
                ledger,
                account_id,
                asset,
                action="opening",
                amount_fen="0",
                costs_fen="0",
                cost_basis_fen="100000",
            ).status_code
            == 200
        )
    before = page(ledger)
    result = send(
        ledger,
        "/investments/holding-transfer/preview",
        {"instrument_id": asset, "source_account_ids": [a, b], "target_account_id": target},
    )
    assert result.status_code == 422
    assert page(ledger) == before


def test_recurring_ownership_moves_but_payment_remains(ledger):
    from test_recurring import drafts, generate, row, setup_plan

    plan, bank, asset = setup_plan(ledger)
    target = account(ledger, "Synthetic Alipay", "0", "securities")
    generate(ledger, plan)
    first = drafts(ledger, plan)[0]
    assert send(ledger, "/recurring/review", {"rows": [row(first)]}).status_code == 200
    before = balances(ledger)
    body = {"instrument_id": asset, "source_account_ids": [bank], "target_account_id": target}
    preview = send(ledger, "/investments/holding-transfer/preview", body)
    assert preview.status_code == 200, preview.text
    committed = send(
        ledger,
        "/investments/holding-transfer/commit",
        {
            **body,
            "ledger_revision": preview.json()["ledger_revision"],
            "preview_token": preview.json()["preview_token"],
        },
    )
    assert committed.status_code == 200, committed.text
    updated = ledger[1].get("/api/v1/recurring").json()[0]
    assert (updated["account_id"], updated["cash_account_id"]) == (target, bank)
    assert balances(ledger) == before
    second = next(d for d in drafts(ledger, plan) if d["status"] == "pending")
    assert send(ledger, "/recurring/review", {"rows": [row(second)]}).status_code == 200
    assert balances(ledger)[target] == "0"
    assert page(ledger)["positions"][0]["quantity"] == "9"


def test_backup_failure_keeps_history_and_balances(ledger, monkeypatch):
    a = account(ledger, "Synthetic bank", "1000000")
    target = account(ledger, "Synthetic Alipay", "0", "securities")
    asset = instrument(ledger)
    assert trade(ledger, a, asset).status_code == 200
    body = {"instrument_id": asset, "source_account_ids": [a], "target_account_id": target}
    preview = send(ledger, "/investments/holding-transfer/preview", body).json()
    before = page(ledger), balances(ledger)

    def fail(*args):
        raise OSError("Synthetic disk failure")

    monkeypatch.setattr("pjz.holding_transfer.write_verified_backup", fail)
    result = send(
        ledger,
        "/investments/holding-transfer/commit",
        {
            **body,
            "ledger_revision": preview["ledger_revision"],
            "preview_token": preview["preview_token"],
        },
    )
    assert result.json()["error"]["code"] == "BACKUP_FAILED"
    assert (page(ledger), balances(ledger)) == before
