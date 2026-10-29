"""Independent historical market-value/cash expectations; synthetic data only."""

from test_daily_ledger import account, send
from test_daily_ledger import ledger as ledger
from test_investment_reports import exported, report, seeded
from test_investments import instrument, price, trade


def feb(ledger, **params):
    return report(ledger, period="custom", start="2026-02-01", end="2026-02-10", **params)


def test_cross_period_dividends_reinvest_split_and_csv(ledger):
    cash, receiver, asset, _ = seeded(ledger)
    assert price(ledger, asset, "11", "2026-01-31").status_code == 200
    result = feb(ledger)
    p = result["performance"]
    assert p["beginning"]["value_fen"] == "220000"
    assert p["beginning"]["positions"][0]["quantity"] == "200"
    assert p["ending"]["positions"][0]["quantity"] == "304"
    assert p["ending"]["value_fen"] == "197600"
    assert p["cash_delta_fen"] == "65700"
    assert p["total_profit_fen"] == "43300"  # 1976 - 2200 + 657 = 433 yuan
    assert feb(ledger, account_id=cash)["performance"] == p
    assert feb(ledger, account_id=receiver)["performance"]["total_profit_fen"] == "0"
    rows = exported(ledger, "report", period="custom", start="2026-02-01", end="2026-02-10")
    assert rows[0]["期间总盈亏（分）"] == "43300"
    assert rows[0]["期初市值（分）"] == "220000"
    assert rows[1]["期间总盈亏（分）"] == ""
    assert feb(ledger)["ledger_revision"] == result["ledger_revision"]


def test_missing_old_future_and_void_boundary_quotes(ledger):
    _, _, asset, _ = seeded(ledger)
    p = feb(ledger)["performance"]
    assert p["total_profit_fen"] is None and p["beginning"]["missing_price_count"] == 1
    assert price(ledger, asset, "11", "2026-01-30").status_code == 200
    assert feb(ledger)["performance"]["beginning"]["value_fen"] is None
    assert price(ledger, asset, "11", "2026-01-31").status_code == 200
    assert feb(ledger)["performance"]["total_profit_fen"] == "43300"
    assert price(ledger, asset, "11", "2026-01-31", revision=1, status="void").status_code == 200
    assert feb(ledger)["performance"]["total_profit_fen"] is None
    # A later split must not change the reconstructed January quantity or use February prices.
    old = report(ledger, period="custom", start="2026-01-10", end="2026-01-31")["performance"]
    assert old["ending"]["positions"][0]["quantity"] == "200"
    assert old["ending"]["value_fen"] is None


def test_unknown_cost_opening_then_boundary_profit(ledger):
    cash = account(ledger, "Synthetic boundary cash", "1000000")
    asset = instrument(ledger)
    assert (
        trade(ledger, cash, asset, action="opening", amount_fen="0", costs_fen="0").status_code
        == 200
    )
    assert price(ledger, asset, "10", "2026-01-31").status_code == 200
    assert price(ledger, asset, "12", "2026-02-10").status_code == 200
    p = feb(ledger)["performance"]
    assert p["beginning"]["positions"][0]["cost_fen"] is None
    assert p["ending"]["value_fen"] == "120000"
    assert p["total_profit_fen"] == "20000"
    january = report(ledger, anchor="2026-01-01")["performance"]
    assert january["status"] == "opening_during_period" and january["total_profit_fen"] is None
    assert january["opening_count"] == 1


def test_empty_before_and_after_history(ledger):
    seeded(ledger)
    p = report(ledger, anchor="2025-01-01")["performance"]
    assert p["total_profit_fen"] == "0" and not p["ending"]["positions"]


def test_same_day_event_requires_price_reconfirmation(ledger):
    cash = account(ledger, "Synthetic confirmation", "1000000")
    asset = instrument(ledger)
    assert trade(ledger, cash, asset).status_code == 200
    assert price(ledger, asset, "10", "2026-01-31").status_code == 200
    assert price(ledger, asset, "9", "2026-02-10").status_code == 200
    dividend = trade(
        ledger,
        cash,
        asset,
        action="cash_dividend",
        quantity="0",
        amount_fen="1000",
        costs_fen="0",
        effective_date="2026-02-10",
    )
    assert dividend.status_code == 200
    p = feb(ledger)["performance"]
    assert p["ending"]["positions"][0]["status"] == "event_requires_confirmation"
    assert p["total_profit_fen"] is None
    assert price(ledger, asset, "9", "2026-02-10", revision=1).status_code == 200
    assert feb(ledger)["performance"]["total_profit_fen"] == "-9000"
    assert (
        send(
            ledger, "/investments/trades/" + dividend.json()["id"] + "/void", {"revision": 1}
        ).status_code
        == 200
    )
    assert feb(ledger)["performance"]["total_profit_fen"] == "-10000"


def test_period_purchase_fee_and_closed_position(ledger):
    cash = account(ledger, "Synthetic buy close", "1000000")
    asset = instrument(ledger)
    assert trade(ledger, cash, asset, effective_date="2026-02-01").status_code == 200
    assert price(ledger, asset, "12", "2026-02-10").status_code == 200
    assert feb(ledger)["performance"]["total_profit_fen"] == "19500"
    sale = trade(
        ledger,
        cash,
        asset,
        action="sell",
        amount_fen="120000",
        costs_fen="500",
        effective_date="2026-02-10",
    )
    assert sale.status_code == 200
    p = feb(ledger)["performance"]
    assert p["ending"]["positions"] == [] and p["total_profit_fen"] == "19000"
    assert (
        send(
            ledger, "/investments/trades/" + sale.json()["id"] + "/void", {"revision": 1}
        ).status_code
        == 200
    )
    assert feb(ledger)["performance"]["total_profit_fen"] == "19500"


def test_multi_account_filter_and_valuation_correction(ledger):
    cash, other, asset, _ = seeded(ledger)
    assert price(ledger, asset, "11", "2026-01-31").status_code == 200
    assert (
        trade(
            ledger,
            other,
            asset,
            quantity="10",
            amount_fen="7000",
            costs_fen="100",
            effective_date="2026-02-06",
        ).status_code
        == 200
    )
    assert feb(ledger, account_id=cash)["performance"]["total_profit_fen"] == "43300"
    assert feb(ledger, account_id=other)["performance"]["total_profit_fen"] == "-600"
    assert feb(ledger)["performance"]["total_profit_fen"] == "42700"
    assert price(ledger, asset, "7", "2026-02-10", revision=1).status_code == 200
    assert feb(ledger)["performance"]["total_profit_fen"] == "58400"


def test_known_opening_during_period_still_not_market_value(ledger):
    cash = account(ledger, "Synthetic injection", "1000000")
    asset = instrument(ledger)
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="opening",
            cost_basis_fen="100000",
            amount_fen="0",
            costs_fen="0",
            effective_date="2026-02-01",
        ).status_code
        == 200
    )
    assert price(ledger, asset, "12", "2026-02-10").status_code == 200
    assert feb(ledger)["performance"]["status"] == "opening_during_period"
    assert feb(ledger)["performance"]["total_profit_fen"] is None
