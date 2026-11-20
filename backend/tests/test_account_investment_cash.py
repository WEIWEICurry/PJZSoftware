"""Synthetic account journals use actual integer cash projections, not holding accounts."""

from test_daily_ledger import account, category, event, send, summary
from test_daily_ledger import ledger as ledger
from test_investments import instrument, trade


def test_investment_cash_account_journal_amounts_filters_and_no_daily_double_count(ledger):
    bank = account(ledger, "Synthetic bank A", "100000")
    other = account(ledger, "Synthetic bank B", "100000")
    platform = account(ledger, "Synthetic holding", "0", "securities")
    fund = instrument(ledger, "000001", "fund", "FUND")

    def save(**extra):
        result = trade(
            ledger, platform, fund, quantity="10", amount_fen="10000", costs_fen="100", **extra
        )
        assert result.status_code == 200, result.text
        return result.json()["id"]

    buy = save(cash_account_id=bank)
    net_buy = save(cash_account_id=other, amount_mode="net")
    result = trade(
        ledger,
        platform,
        fund,
        action="sell",
        cash_account_id=other,
        quantity="5",
        amount_fen="5000",
        costs_fen="50",
    )
    assert result.status_code == 200, result.text
    sale = result.json()["id"]
    result = trade(
        ledger,
        platform,
        fund,
        action="cash_dividend",
        cash_account_id=bank,
        quantity="0",
        amount_fen="1000",
        costs_fen="0",
    )
    assert result.status_code == 200, result.text
    dividend = result.json()["id"]
    result = trade(
        ledger,
        platform,
        fund,
        action="reinvest",
        cash_account_id=bank,
        quantity="1",
        amount_fen="1000",
        costs_fen="10",
    )
    assert result.status_code == 200, result.text
    reinvest = result.json()["id"]
    result = trade(
        ledger, platform, fund, action="reinvest", quantity="1", amount_fen="1000", costs_fen="0"
    )
    assert result.status_code == 200
    no_cash = result.json()["id"]
    voided = save(cash_account_id=bank)
    assert send(ledger, f"/investments/trades/{voided}/void", {"revision": 1}).status_code == 200
    daily = event(ledger, bank, "200")
    before = ledger[0].metadata()

    def query(**extra):
        response = ledger[1].get(
            "/api/v1/events",
            params={
                "start": "2026-01-01",
                "end": "2026-01-31",
                "include_investments": True,
                **extra,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    rows = query(account_id=bank, kind="investment")["items"]
    assert {r["id"]: r["cash_delta_fen"] for r in rows} == {
        buy: "-10100",
        dividend: "1000",
        reinvest: "-10",
        voided: None,
    }
    assert all(
        r["account_id"] == platform and r["investment_cash_account_id"] == bank for r in rows
    )
    assert all(r["instrument_code"] == "000001" and not r["covered_by_history"] for r in rows)
    other_rows = query(account_id=other, kind="investment")["items"]
    assert {r["id"]: r["cash_delta_fen"] for r in other_rows} == {net_buy: "-10000", sale: "4950"}
    assert query(account_id=platform, kind="investment")["total"] == 0
    assert no_cash not in {r["id"] for r in query()["items"]}
    assert all(r["kind"] != "investment" for r in query(include_investments=False)["items"])
    filtered = query(account_id=bank, category_id=category(ledger, "餐饮"))
    assert [r["id"] for r in filtered["items"]] == [daily["id"]]
    expected_ids = [r["id"] for r in query()["items"]]
    assert query(limit=2)["total"] == len(expected_ids)
    assert [r["id"] for r in query(limit=2, offset=2)["items"]] == expected_ids[2:4]
    assert summary(ledger)["income_fen"] == "0"
    assert summary(ledger)["expense_fen"] == "200"
    assert ledger[0].metadata() == before


def test_same_holding_cash_account_and_non_cash_opening_exclusion(ledger):
    bank = account(ledger, "Synthetic same account", "100000")
    fund = instrument(ledger, "000002", "fund", "FUND")
    result = trade(
        ledger,
        bank,
        fund,
        action="opening",
        quantity="10",
        amount_fen="0",
        costs_fen="0",
        cost_basis_fen="10000",
    )
    assert result.status_code == 200
    opening = result.json()["id"]
    result = trade(ledger, bank, fund, amount_fen="10000", costs_fen="100")
    assert result.status_code == 200
    response = ledger[1].get(
        "/api/v1/events",
        params={
            "start": "2026-01-01",
            "end": "2026-01-31",
            "account_id": bank,
            "include_investments": True,
            "kind": "investment",
        },
    )
    assert response.status_code == 200
    rows = response.json()["items"]
    assert len(rows) == 1 and rows[0]["id"] != opening
    assert rows[0]["investment_cash_account_id"] == bank
    assert rows[0]["cash_delta_fen"] == "-10100"
