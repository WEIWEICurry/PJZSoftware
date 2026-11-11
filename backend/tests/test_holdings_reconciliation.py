"""Synthetic holdings screenshot and read-only accounting acceptance."""

from dataclasses import asdict

import pytest
from pjz.domain import RuleError
from pjz.receipt_ocr import TextLine, parse_holding
from pjz.reconciliation_domain import compare_quantity, reference_value
from test_daily_ledger import account, send
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, price, trade


def screenshot_lines():
    return [
        TextLine("资产详情", 300, 100, 30, 0.99),
        TextLine("合成储能基金A", 30, 200, 30, 0.99),
        TextLine("000001", 30, 250, 20, 0.99),
        TextLine("中高风险", 200, 250, 20, 0.99),
        TextLine("持有金额", 30, 600, 25, 0.99),
        TextLine("1,234.56", 210, 600, 25, 0.99),
        TextLine("待确认金额", 500, 600, 25, 0.99),
        TextLine("0.00", 700, 600, 25, 0.99),
        TextLine("持仓成本价 1.5000", 30, 650, 25, 0.99),
        TextLine("持有份额 800.12", 500, 650, 25, 0.99),
        TextLine("日涨幅 +1.00%", 30, 700, 25, 0.99),
        TextLine("基金净值", 500, 700, 25, 0.99),
        TextLine("1.5430(11-10)", 700, 700, 25, 0.99),
    ]


def test_holding_parser_keeps_columns_separate_and_retains_date_precision():
    result = parse_holding(screenshot_lines())
    assert (result.product, result.code) == ("合成储能基金A", "000001")
    assert (result.quantity, result.amount, result.pending) == ("800.12", "1234.56", "0.00")
    assert (result.unit_nav, result.nav_month_day, result.nav_date) == ("1.5430", "11-10", None)
    assert result.cost_price == "1.5000"
    assert result.warnings
    lines = screenshot_lines()
    lines[-1] = TextLine("1.5430(2026-11-10)", 700, 700, 25, 0.99)
    assert parse_holding(lines).nav_date == "2026-11-10"
    lines[-1] = TextLine("1.5430(13-40)", 700, 700, 25, 0.99)
    assert parse_holding(lines).nav_month_day is None
    missing = parse_holding(lines[:9])
    assert missing.quantity is None and missing.amount == "1234.56"
    with pytest.raises(RuleError, match="OCR_UNSUPPORTED_HOLDING"):
        parse_holding([TextLine("买入成功", 0, 0, 20, 0.99)])


@pytest.mark.parametrize(
    ("local", "shown", "status", "delta"),
    [
        ("10.12", "10.12", "exact", "0"),
        ("10.12499999", "10.12", "display", "0.00499999"),
        ("10.125", "10.12", "different", "0.005"),
        ("10.125", "10.13", "display", "-0.005"),
        ("0", "2.00", "different", "-2"),
    ],
)
def test_quantity_precision_is_explicit(local, shown, status, delta):
    assert compare_quantity(local, shown) == (status, delta)
    assert reference_value("3", "1.005") == "302"
    assert reference_value("3", None) is None


def row(asset, **changes):
    return {
        "instrument_id": asset,
        "quantity": "2.12",
        "amount_fen": "424",
        "unit_nav": "2",
        "nav_date": "2026-01-11",
        "pending_fen": "1000",
        **changes,
    }


def test_historical_reconcile_is_read_only_with_different_nav_dates_and_unprovided(ledger):
    holding = account(ledger, "Synthetic holding", "100000", "securities")
    fund = instrument(ledger, "000001", "fund", "FUND")
    other = instrument(ledger, "000002", "fund", "FUND")
    absent = instrument(ledger, "000003", "fund", "FUND")
    assert (
        trade(
            ledger, holding, fund, quantity="2.12345678", amount_fen="500", costs_fen="0"
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            holding,
            fund,
            quantity="1",
            amount_fen="200",
            costs_fen="0",
            effective_date="2026-01-12",
        ).status_code
        == 200
    )
    assert (
        trade(ledger, holding, other, quantity="4", amount_fen="400", costs_fen="0").status_code
        == 200
    )
    assert price(ledger, fund, "1.5", "2026-01-10").status_code == 200
    before, revision = page(ledger), ledger[0].metadata()["revision"]
    payload = {
        "account_id": holding,
        "as_of": "2026-01-11",
        "rows": [row(fund), row(absent, quantity="3", amount_fen="300", unit_nav="1")],
    }
    response = send(ledger, "/investments/holdings/reconcile", payload)
    assert response.status_code == 200, response.text
    result = response.json()
    first = result["rows"][0]
    assert first["local_quantity"] == "2.12345678"
    assert (first["quantity_status"], first["quantity_delta"]) == ("display", "0.00345678")
    assert (first["reference_value_fen"], first["value_delta_fen"]) == ("425", "1")
    assert first["local_price_date"] == "2026-01-10" and not first["same_price_date"]
    assert first["pending_fen"] == "1000" and first["local_value_fen"] == "319"
    assert result["rows"][1]["local_quantity"] == "0"
    assert result["unprovided"] == [
        {"instrument_id": other, "name": "Synthetic 000002", "quantity": "4"}
    ]
    assert page(ledger) == before and ledger[0].metadata()["revision"] == revision


def test_missing_price_duplicate_rows_invalid_input_and_auth(ledger, monkeypatch):
    holding = account(ledger, "Synthetic holding", "100000", "securities")
    fund = instrument(ledger, "000001", "fund", "FUND")
    assert (
        trade(ledger, holding, fund, quantity="2", costs_fen="0", amount_fen="100").status_code
        == 200
    )
    payload = {
        "account_id": holding,
        "as_of": "2026-01-11",
        "rows": [row(fund, unit_nav=None, nav_date=None, amount_fen=None, pending_fen=None)],
    }
    result = send(ledger, "/investments/holdings/reconcile", payload).json()["rows"][0]
    assert (
        result["local_value_fen"] is None
        and result["reference_value_fen"] is None
        and result["value_delta_fen"] is None
    )
    duplicate = send(
        ledger, "/investments/holdings/reconcile", {**payload, "rows": [row(fund), row(fund)]}
    )
    assert (
        duplicate.status_code == 422
        and duplicate.json()["error"]["code"] == "HOLDING_DUPLICATE_FUND"
    )
    for rows in (
        [],
        [row(fund)] * 21,
        [row(fund, quantity="1e2")],
        [row(fund, amount_fen="-1")],
        [row(fund, nav_date="2026-01-12")],
    ):
        assert (
            send(ledger, "/investments/holdings/reconcile", {**payload, "rows": rows}).status_code
            == 422
        )
    assert ledger[1].post("/api/v1/investments/holdings/reconcile", json=payload).status_code == 403
    monkeypatch.setattr("pjz.investment_api.recognize_lines", lambda data: screenshot_lines())
    _, client, headers = ledger
    revision = ledger[0].metadata()["revision"]
    response = client.post(
        "/api/v1/investments/holding-preview",
        files={"file": ("synthetic.png", b"synthetic", "image/png")},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == asdict(parse_holding(screenshot_lines()))
    assert ledger[0].metadata()["revision"] == revision
