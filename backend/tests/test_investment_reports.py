"""Synthetic independent expectations for investment attribution and CSV exports."""

import csv
import io
import uuid
from datetime import date

import pytest
from pjz.accounting import Accounting
from pjz.investment_report_domain import investment_bounds
from test_daily_ledger import account, send, summary
from test_daily_ledger import ledger as ledger
from test_investments import instrument, price, trade


def report(ledger, **params):
    response = ledger[1].get(
        "/api/v1/investment-reports", params={"period": "month", "anchor": "2026-02-10", **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def exported(ledger, dataset, **params):
    response = ledger[1].get(
        "/api/v1/investment-reports/export",
        params={"period": "month", "anchor": "2026-02-10", "dataset": dataset, **params},
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["cache-control"] == "no-store"
    reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    rows = list(reader)
    assert all(None not in row for row in rows)
    return rows


def seeded(ledger):
    cash = account(ledger, "Synthetic report A", "1000000")
    receiver = account(ledger, "Synthetic report B", "500000")
    asset = instrument(ledger, "000001", "fund", "FUND")
    assert trade(ledger, cash, asset, effective_date="2026-01-10").status_code == 200
    assert (
        trade(ledger, cash, asset, amount_fen="120000", effective_date="2026-01-11").status_code
        == 200
    )
    sale = trade(
        ledger,
        cash,
        asset,
        action="sell",
        quantity="50",
        amount_fen="65000",
        costs_fen="200",
        effective_date="2026-02-01",
    ).json()["id"]
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="cash_dividend",
            quantity="0",
            amount_fen="1000",
            costs_fen="0",
            cash_account_id=receiver,
            effective_date="2026-02-02",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="reinvest",
            quantity="2",
            amount_fen="2000",
            costs_fen="100",
            effective_date="2026-02-03",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="split",
            quantity="304",
            amount_fen="0",
            costs_fen="0",
            split_from_quantity="152",
            note="Synthetic confirmed split",
            effective_date="2026-02-04",
        ).status_code
        == 200
    )
    assert price(ledger, asset, "6.5", "2026-02-10").status_code == 200
    return cash, receiver, asset, sale


def test_period_uses_prior_costs_and_never_deducts_fees_twice(ledger):
    cash, receiver, asset, sale = seeded(ledger)
    result = report(ledger)
    assert result["totals"] == {
        "record_count": 4,
        "buy_outflow_fen": "0",
        "sell_inflow_fen": "64800",
        "realized_fen": "9550",
        "cash_dividends_fen": "1000",
        "reinvested_dividends_fen": "2000",
        "fees_fen": "300",
        "cash_delta_fen": "65700",
        "realized_and_dividends_fen": "12550",
    }
    sold = next(r for r in result["entries"]["items"] if r["id"] == sale)
    assert sold["allocated_cost_fen"] == "55250"
    assert sold["realized_fen"] == "9550"
    dividend = next(r for r in result["entries"]["items"] if r["action"] == "cash_dividend")
    assert dividend["cash_account_id"] == receiver and dividend["account_id"] == cash
    assert result["contributions"][0]["realized_and_dividends_fen"] == "12550"
    january = report(ledger, anchor="2026-01-01")["totals"]
    assert january["buy_outflow_fen"] == "221000" and january["fees_fen"] == "1000"
    year = report(ledger, period="year", anchor="2026-01-01")["totals"]
    assert year["cash_delta_fen"] == "-155300" and year["fees_fen"] == "1300"
    assert report(ledger, account_id=receiver)["totals"]["record_count"] == 0
    assert exported(ledger, "valuations", account_id=receiver) == []
    assert report(ledger, account_id=cash, instrument_id=asset)["totals"] == result["totals"]
    assert summary(ledger)["income_fen"] == summary(ledger)["expense_fen"] == "0"


def test_same_instrument_accounts_keep_independent_costs(ledger):
    cash, other, asset, _ = seeded(ledger)
    assert (
        trade(
            ledger,
            other,
            asset,
            action="opening",
            quantity="10",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen="10000",
            effective_date="2026-02-08",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            other,
            asset,
            action="sell",
            quantity="2",
            amount_fen="2600",
            costs_fen="0",
            effective_date="2026-02-09",
        ).status_code
        == 200
    )
    result = report(ledger)
    assert result["totals"]["realized_fen"] == "10150"
    assert result["totals"]["sell_inflow_fen"] == "67400"
    assert result["totals"]["cash_delta_fen"] == "68300"
    assert result["totals"]["record_count"] == 6
    assert len(result["contributions"]) == 1
    assert report(ledger, account_id=other)["totals"]["realized_fen"] == "600"
    assert report(ledger, account_id=cash)["totals"]["realized_fen"] == "9550"
    groups = [g for g in result["current_allocation"]["groups"] if g["group_by"] == "account"]
    assert {g["id"]: g["share_bps"] for g in groups} == {cash: "9744", other: "256"}


def test_current_allocation_is_not_a_historical_snapshot_and_unknowns(ledger):
    cash = account(ledger, "Synthetic allocation", "100000")
    fund = instrument(ledger, "000001", "fund", "FUND")
    stock = instrument(ledger)
    assert (
        trade(
            ledger, cash, fund, action="opening", quantity="1", amount_fen="0", costs_fen="0"
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            stock,
            action="opening",
            quantity="2",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen="2000",
        ).status_code
        == 200
    )
    price(ledger, fund, "10", "2026-01-20")
    result = report(ledger, anchor="2025-01-01")
    assert result["totals"]["record_count"] == 0
    allocation = result["current_allocation"]
    assert allocation["as_of_date"] == date.today().isoformat()
    assert allocation["known_value_fen"] == "1000" and allocation["total_value_fen"] is None
    assert all(g["share_bps"] is None for g in allocation["groups"])
    account_group = next(g for g in allocation["groups"] if g["group_by"] == "account")
    assert account_group["value_fen"] is None and account_group["known_value_fen"] == "1000"
    price(ledger, stock, "10", "2026-01-21")
    result = report(ledger, kind="fund")
    assert result["current_allocation"]["total_value_fen"] == "3000"
    assert all(g["share_bps"] == "3333" for g in result["current_allocation"]["groups"])
    rows = exported(ledger, "positions", anchor="2025-01-01")
    assert len(rows) == 2
    fund_row = next(r for r in rows if r["标的ID"] == fund)
    assert fund_row["剩余成本（元）"] == "" and fund_row["成本状态"] == "成本待补"
    assert fund_row["占比基点"] == "3333"
    assert fund_row["价格日期"] == "2026-01-20"


def test_zero_value_allocation_and_liquidated_positions(ledger):
    cash = account(ledger, "Synthetic zero allocation", "100000")
    asset = instrument(ledger, "000001", "fund", "FUND")
    trade(ledger, cash, asset, quantity="1", amount_fen="1000", costs_fen="0")
    price(ledger, asset, "0.000001")
    result = report(ledger)["current_allocation"]
    assert result["total_value_fen"] == "0"
    assert all(g["share_bps"] is None for g in result["groups"])
    trade(ledger, cash, asset, action="sell", quantity="1", amount_fen="1000", costs_fen="0")
    assert report(ledger)["current_allocation"]["selected_position_count"] == 0
    assert exported(ledger, "positions") == []


def test_void_list_does_not_change_totals_and_csv_includes_all_pages(ledger):
    cash, _, asset, _ = seeded(ledger)
    for index in range(23):
        assert (
            trade(
                ledger,
                cash,
                asset,
                action="cash_dividend",
                quantity="0",
                amount_fen="100",
                costs_fen="0",
                effective_date="2026-02-05",
                note=f"Synthetic row {index}",
            ).status_code
            == 200
        )
    victim = report(ledger)["entries"]["items"][0]
    assert (
        send(
            ledger, f"/investments/trades/{victim['id']}/void", {"revision": victim["revision"]}
        ).status_code
        == 200
    )
    result = report(ledger)
    assert result["entries"]["total"] == 26 and len(result["entries"]["items"]) == 20
    second = report(ledger, offset=20)
    assert len(second["entries"]["items"]) == 6 and second["totals"] == result["totals"]
    assert report(ledger, include_void=True)["entries"]["total"] == 27
    assert report(ledger, include_void=True)["totals"] == result["totals"]
    assert len(exported(ledger, "trades")) == 26
    all_rows = exported(ledger, "trades", include_void=True)
    assert len(all_rows) == 27
    void = next(r for r in all_rows if r["记录ID"] == victim["id"])
    assert void["实际现金变动（元）"] == "" and "不计入" in void["状态"]


def test_four_csv_exact_values_scope_formula_escape_and_no_writes(ledger):
    cash = account(ledger, "+Synthetic account", "100000")
    response = send(
        ledger,
        "/investments/instruments",
        {"market": "FUND", "code": "000001", "name": "=SUM(1,2)", "kind": "fund"},
    )
    asset = response.json()["id"]
    trade(
        ledger,
        cash,
        asset,
        quantity="1.00000001",
        amount_fen="1000",
        costs_fen="1",
        effective_date="2026-02-01",
        note='\t=HYPERLINK("synthetic")\n合成,备注',
    )
    price(ledger, asset, "10", "2026-02-02")
    price(ledger, asset, "11", "2026-02-03")
    price(ledger, asset, "11", "2026-02-03", 1, "void")
    before_revision = ledger[0].metadata()["revision"]
    before_accounts = Accounting(ledger[0].engine).accounts()
    for dataset in ("report", "trades", "positions", "valuations"):
        rows = exported(ledger, dataset, account_id=cash)
        assert rows
        assert all(r["账本版本"] == str(before_revision) for r in rows)
        assert all(r["代码"] in ("", "000001") for r in rows)
        assert any(r["标的名称"] == "'=SUM(1,2)" for r in rows)
    trades = exported(ledger, "trades")
    assert trades[0]["持仓账户"] == "'+Synthetic account"
    assert trades[0]["备注"].startswith("'\t=HYPERLINK")
    assert trades[0]["成交或净分红（分）"] == "1000"
    assert trades[0]["实际现金变动（元）"] == "-10.01"
    assert trades[0]["份额"] == "1.00000001"
    valuations = exported(ledger, "valuations")
    assert len(valuations) == 2 and {r["状态"] for r in valuations} == {"有效", "已作废"}
    totals = exported(ledger, "report")[0]
    assert totals["买入实际扣款（元）"] == "10.01"
    assert totals["已计入费用（元）"] == "0.01"
    assert ledger[0].metadata()["revision"] == before_revision
    assert Accounting(ledger[0].engine).accounts() == before_accounts


@pytest.mark.parametrize("dataset", ["report", "trades", "positions", "valuations"])
def test_export_caps_are_rejections_not_truncation(ledger, monkeypatch, dataset):
    seeded(ledger)
    monkeypatch.setattr("pjz.investment_reports.MAX_EXPORT_ROWS", 0)
    response = ledger[1].get(
        "/api/v1/investment-reports/export",
        params={"dataset": dataset, "period": "month", "anchor": "2026-02-01"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPORT_EXPORT_TOO_LARGE"


@pytest.mark.parametrize(
    "period,anchor,start,end,first,last",
    [
        ("month", date(2024, 2, 15), None, None, date(2024, 2, 1), date(2024, 2, 29)),
        ("year", date(2026, 5, 1), None, None, date(2026, 1, 1), date(2026, 10, 28)),
        (
            "custom",
            date(2026, 1, 1),
            date(2026, 10, 1),
            date(2026, 12, 1),
            date(2026, 10, 1),
            date(2026, 10, 28),
        ),
    ],
)
def test_period_boundaries(period, anchor, start, end, first, last):
    assert investment_bounds(period, anchor, start, end, date(2026, 10, 28))[:2] == (first, last)


@pytest.mark.parametrize(
    "params",
    [
        {"period": "custom", "start": "2026-02-02", "end": "2026-02-01"},
        {"period": "custom"},
        {"anchor": "2099-01-01"},
        {"account_id": str(uuid.uuid4())},
        {"instrument_id": str(uuid.uuid4())},
        {"kind": "other"},
    ],
)
def test_invalid_period_and_filters(ledger, params):
    response = ledger[1].get(
        "/api/v1/investment-reports", params={"period": "month", "anchor": "2026-02-01", **params}
    )
    assert response.status_code == 422


def test_event_price_gate_and_historical_edits_are_reflected(ledger):
    cash, _, asset, sale = seeded(ledger)
    before = report(ledger)
    assert (
        send(
            ledger,
            f"/investments/trades/{sale}",
            {
                "account_id": cash,
                "instrument_id": asset,
                "action": "sell",
                "effective_date": "2026-02-01",
                "quantity": "50",
                "amount_fen": "60000",
                "costs_fen": "200",
                "revision": 1,
            },
            "PUT",
        ).status_code
        == 200
    )
    after = report(ledger)
    assert after["totals"]["realized_fen"] == "4550"
    assert before["totals"]["realized_fen"] == "9550"
    price(ledger, asset, "6.5", "2026-02-10", 1, "void")
    result = report(ledger)
    assert result["current_allocation"]["total_value_fen"] is None
    assert result["totals"] == after["totals"]
    assert exported(ledger, "positions")[0]["市值（元）"] == ""


def test_net_amount_buy_sell_fees_are_attributed_once(ledger):
    cash = account(ledger, "Synthetic net reporting", "100000")
    fund = instrument(ledger, "000001", "fund", "FUND")
    assert (
        trade(
            ledger,
            cash,
            fund,
            quantity="3",
            amount_fen="10001",
            costs_fen="1",
            amount_mode="net",
            effective_date="2026-02-01",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            fund,
            action="sell",
            quantity="1",
            amount_fen="4000",
            costs_fen="1",
            amount_mode="net",
            effective_date="2026-02-02",
        ).status_code
        == 200
    )
    totals = report(ledger)["totals"]
    assert (
        totals["buy_outflow_fen"],
        totals["sell_inflow_fen"],
        totals["fees_fen"],
        totals["cash_delta_fen"],
        totals["realized_fen"],
    ) == ("10001", "4000", "2", "-6001", "666")
    assert "total_profit_fen" not in totals
    debt = account(ledger, "Synthetic excluded loan", "0", "liability")
    response = ledger[1].get("/api/v1/investment-reports", params={"account_id": debt})
    assert response.status_code == 422
    assert all(a["kind"] not in ("liability", "receivable") for a in report(ledger)["accounts"])
