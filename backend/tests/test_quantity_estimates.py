"""Independent fund-unit rounding and exact-date read-only estimates."""

import pytest
from pjz.domain import RuleError
from pjz.investment_domain import estimate_fund_quantity
from test_daily_ledger import ledger as ledger
from test_daily_ledger import send
from test_investments import instrument, price


@pytest.mark.parametrize(
    ("amount", "fee", "mode", "nav", "expected"),
    [
        (1000, 1, "net", "1.6586", "6.02"),
        (1000, 1, "net", "1.6792", "5.95"),
        (1000, 1, "gross", "2", "5.00"),
        (1000, 1, "net", "2", "5.00"),
        (1000, 2, "net", "2", "4.99"),
        (1, 0, "net", "2", "0.01"),
    ],
)
def test_independent_quantity_examples(amount, fee, mode, nav, expected):
    assert estimate_fund_quantity(amount, fee, mode, nav) == expected


@pytest.mark.parametrize(
    ("amount", "fee", "nav", "code"),
    [
        (1, 1, "2", "FEE_EXCEEDS_AMOUNT"),
        (0, 0, "2", "INVALID_AMOUNT"),
        (1, 0, "100", "ESTIMATE_TOO_SMALL"),
    ],
)
def test_estimate_rejects_invalid_or_unrepresentable_units(amount, fee, nav, code):
    with pytest.raises(RuleError, match=code):
        estimate_fund_quantity(amount, fee, "net", nav)


def test_exact_active_nav_only_no_fallback_no_writes_and_auth(ledger):
    fund = instrument(ledger, "000001", "fund", "FUND")
    assert price(ledger, fund, "1.6586", "2026-01-10").status_code == 200
    assert price(ledger, fund, "1.6792", "2026-01-11").status_code == 200
    assert price(ledger, fund, "1.6792", "2026-01-11", revision=1, status="void").status_code == 200
    revision = ledger[0].metadata()["revision"]
    rows = [
        {
            "id": str(i),
            "instrument_id": fund,
            "nav_date": day,
            "amount_fen": "1000",
            "costs_fen": "1",
        }
        for i, day in enumerate(["2026-01-10", "2026-01-11", "2026-01-12"])
    ]
    response = send(ledger, "/investments/quantity-estimates", {"rows": rows})
    assert response.status_code == 200, response.text
    assert response.json()[0]["quantity"] == "6.02"
    assert all(
        r["quantity"] is None and r["code"] == "ESTIMATE_NAV_MISSING" for r in response.json()[1:]
    )
    assert ledger[0].metadata()["revision"] == revision
    assert send(ledger, "/investments/quantity-estimates", {"rows": rows * 34}).status_code == 422
    assert (
        ledger[1].post("/api/v1/investments/quantity-estimates", json={"rows": rows}).status_code
        == 403
    )
