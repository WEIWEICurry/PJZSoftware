"""Synthetic atomic receipt batch acceptance."""

import uuid

from test_daily_ledger import account, send, summary
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page


def row(holding, bank, fund, **changes):
    return {
        "account_id": holding,
        "cash_account_id": bank,
        "instrument_id": fund,
        "effective_date": "2026-01-10",
        "nav_date": "2026-01-09",
        "quantity": "93.08000001",
        "amount_fen": "10000",
        "costs_fen": "12",
        **changes,
    }


def setup(ledger):
    holding = account(ledger, "Synthetic holding", "0", "securities")
    bank = account(ledger, "Synthetic payment", "100000")
    fund = instrument(ledger, "000001", "fund", "FUND")
    return holding, bank, fund


def test_batch_is_exact_idempotent_and_duplicate_safe(ledger):
    holding, bank, fund = setup(ledger)
    first = row(holding, bank, fund)
    second = row(holding, bank, fund, quantity="2", amount_fen="200", costs_fen="1")
    payload = {"rows": [first, second]}
    before = summary(ledger)
    key = str(uuid.uuid4())
    response = send(ledger, "/investments/receipt-batches", payload, key=key)
    assert response.status_code == 200, response.text
    assert len(response.json()["ids"]) == 2
    result = page(ledger)
    assert result["positions"][0]["quantity"] == "95.08000001"
    assert result["positions"][0]["cost_fen"] == "10200"
    assert summary(ledger)["expense_fen"] == before["expense_fen"]
    accounts = ledger[1].get("/api/v1/accounts").json()
    assert next(a for a in accounts if a["id"] == bank)["balance_fen"] == "89800"
    revision = ledger[0].metadata()["revision"]
    repeated = send(ledger, "/investments/receipt-batches", payload, key=key)
    assert repeated.json() == response.json()
    assert ledger[0].metadata()["revision"] == revision
    duplicate = send(ledger, "/investments/receipt-batches", {"rows": [first]})
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "RECEIPT_POSSIBLE_DUPLICATE"
    assert page(ledger) == result
    allowed = send(
        ledger,
        "/investments/receipt-batches",
        {"rows": [{**first, "allow_possible_duplicate": True}]},
    )
    assert allowed.status_code == 200
    assert page(ledger)["positions"][0]["quantity"] == "188.16000002"


def test_batch_duplicate_inside_batch_and_insufficient_balance_roll_back(ledger):
    holding, bank, fund = setup(ledger)
    first = row(holding, bank, fund)
    initial = page(ledger)
    revision = ledger[0].metadata()["revision"]
    duplicate = send(ledger, "/investments/receipt-batches", {"rows": [first, first]})
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "RECEIPT_POSSIBLE_DUPLICATE"
    assert page(ledger) == initial and ledger[0].metadata()["revision"] == revision
    second = {**first, "quantity": "10", "amount_fen": "1000000"}
    failed = send(ledger, "/investments/receipt-batches", {"rows": [first, second]})
    assert failed.status_code == 422
    assert page(ledger) == initial and ledger[0].metadata()["revision"] == revision


def test_batch_rejects_invalid_input_and_requires_local_auth(ledger):
    holding, bank, fund = setup(ledger)
    first = row(holding, bank, fund)
    cases = [
        [],
        [first] * 21,
        [{**first, "nav_date": "2026-01-11"}],
        [{**first, "action": "sell"}],
        [{**first, "amount_mode": "gross"}],
        [{**first, "quantity": "0"}],
        [{**first, "costs_fen": "10000"}],
        [{**first, "cash_account_id": None}],
    ]
    for rows in cases:
        assert send(ledger, "/investments/receipt-batches", {"rows": rows}).status_code == 422
    stock = instrument(ledger)
    response = send(
        ledger, "/investments/receipt-batches", {"rows": [{**first, "instrument_id": stock}]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RECEIPT_FUND_REQUIRED"
    assert (
        ledger[1].post("/api/v1/investments/receipt-batches", json={"rows": [first]}).status_code
        == 403
    )


def test_concurrent_batches_only_insert_once(ledger):
    from concurrent.futures import ThreadPoolExecutor

    holding, bank, fund = setup(ledger)
    payload = {"rows": [row(holding, bank, fund)]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: send(ledger, "/investments/receipt-batches", payload), range(2))
        )
    assert sorted(response.status_code for response in results) == [200, 422]
    assert len(page(ledger)["trades"]) == 1
    assert page(ledger)["positions"][0]["quantity"] == "93.08000001"
