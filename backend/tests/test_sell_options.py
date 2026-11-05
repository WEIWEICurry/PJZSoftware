"""Synthetic dated sell options never infer ownership from payment accounts."""

import uuid

from test_daily_ledger import account
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, trade


def test_dated_sell_options_and_final_replay(ledger):
    platform = account(ledger, "Synthetic platform", "0", "securities")
    bank = account(ledger, "Synthetic bank", "1000000")
    asset = instrument(ledger)
    other = instrument(ledger, "600002")

    def options(account_id, day):
        r = ledger[1].get(
            "/api/v1/investments/sell-options",
            params={"account_id": account_id, "effective_date": day},
        )
        assert r.status_code == 200, r.text
        return r.json()

    assert (
        trade(
            ledger,
            platform,
            asset,
            cash_account_id=bank,
            quantity="10",
            amount_fen="10000",
            costs_fen="0",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            platform,
            asset,
            action="sell",
            cash_account_id=bank,
            quantity="10",
            amount_fen="12000",
            costs_fen="0",
            effective_date="2026-01-20",
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger,
            bank,
            other,
            quantity="5",
            amount_fen="1000",
            costs_fen="0",
            effective_date="2026-01-25",
        ).status_code
        == 200
    )
    before = page(ledger)
    assert options(platform, "2026-01-09") == []
    assert options(platform, "2026-01-10") == [{"instrument_id": asset, "quantity": "10"}]
    assert options(platform, "2026-01-19") == [{"instrument_id": asset, "quantity": "10"}]
    assert options(platform, "2026-01-20") == []
    assert options(bank, "2026-01-19") == []
    assert options(bank, "2026-01-25") == [{"instrument_id": other, "quantity": "5"}]
    assert options(str(uuid.uuid4()), "2026-01-19") == []
    assert page(ledger) == before
    # Historical visibility is not a guarantee: a later full sale would oversell.
    assert (
        trade(
            ledger,
            platform,
            asset,
            action="sell",
            quantity="1",
            amount_fen="100",
            costs_fen="0",
            effective_date="2026-01-19",
            cash_account_id=bank,
        ).status_code
        == 422
    )
    assert page(ledger) == before
    assert (
        ledger[1]
        .get(
            "/api/v1/investments/sell-options",
            params={"account_id": platform, "effective_date": "2099-01-01"},
        )
        .status_code
        == 422
    )
    assert (
        ledger[1]
        .get(
            "/api/v1/investments/sell-options",
            params={"account_id": "bad", "effective_date": "2026-01-19"},
        )
        .status_code
        == 422
    )
