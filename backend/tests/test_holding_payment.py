"""Independent cash and merged moving-cost acceptance; synthetic records only."""

from pjz.accounting import Accounting
from pjz.storage import LedgerStore
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
    from pjz.investments import Investments

    restored = LedgerStore(ledger[0].restore(ledger[0].backup()))
    try:
        assert Investments(Accounting(restored.engine)).page()["positions"] == before["positions"]
        assert {a["id"]: a["balance_fen"] for a in Accounting(restored.engine).accounts()} == b
    finally:
        restored.close()


def test_retired_holding_transfer_endpoints(ledger):
    paths = ledger[1].app.openapi()["paths"]
    for action in ("preview", "commit"):
        path = "/investments/holding-transfer/" + action
        assert send(ledger, path, {}).status_code == 404
        assert "/api/v1" + path not in paths
