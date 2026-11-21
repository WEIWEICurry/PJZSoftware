"""Independent synthetic after-event balances across hidden cash movements."""

from test_daily_ledger import account, event, send
from test_daily_ledger import ledger as ledger
from test_investments import instrument, trade


def journal(ledger, **extra):
    response = ledger[1].get(
        "/api/v1/events",
        params={
            "start": "2026-01-01",
            "end": "2026-02-28",
            "limit": 100,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def effects(ledger, identifier, **extra):
    rows = journal(ledger, **extra)["items"]
    return next(row["cash_effects"] for row in rows if row["id"] == identifier)


def test_after_event_balances_survive_filters_pages_and_investment_hiding(ledger):
    bank = account(ledger, "Synthetic bank", "100000")
    cash = account(ledger, "Synthetic cash", "0", "cash")
    platform = account(ledger, "Synthetic platform", "0", "securities")
    expense = event(ledger, bank, "1230")
    transfer = event(
        ledger,
        bank,
        "20000",
        "transfer",
        target_account_id=cash,
        fee_fen="100",
        category_id=next(
            c["id"] for c in ledger[1].get("/api/v1/categories").json() if c["name"] == "手续费"
        ),
    )
    event(ledger, bank, "5000", "income")
    refund = event(
        ledger, bank, "230", "refund", original_event_id=expense["id"], effective_date="2026-01-11"
    )
    adjustment = event(
        ledger, bank, "-100", "adjustment", note="Synthetic correction", effective_date="2026-01-12"
    )
    fund = instrument(ledger, "000001", "fund", "FUND")
    bought = trade(
        ledger,
        platform,
        fund,
        cash_account_id=bank,
        quantity="1",
        amount_fen="1000",
        costs_fen="10",
        effective_date="2026-01-13",
    )
    assert bought.status_code == 200
    last = event(ledger, bank, "200", effective_date="2026-02-01")
    before = ledger[0].metadata()
    assert effects(ledger, expense["id"])[0]["balance_fen"] == "98770"
    both = {
        r["account_id"]: (r["delta_fen"], r["balance_fen"]) for r in effects(ledger, transfer["id"])
    }
    assert both == {bank: ("-20100", "78670"), cash: ("20000", "20000")}
    assert effects(ledger, transfer["id"], account_id=cash)[0]["delta_fen"] == "20000"
    assert len(effects(ledger, transfer["id"], account_id=cash)) == 1
    assert effects(ledger, refund["id"])[0]["balance_fen"] == "83900"
    assert effects(ledger, adjustment["id"])[0]["balance_fen"] == "83800"
    assert (
        effects(ledger, bought.json()["id"], include_investments=True)[0]["balance_fen"] == "82790"
    )
    february = journal(ledger, account_id=bank, start="2026-02-01", kind="expense", limit=1)
    assert february["items"][0]["cash_effects"][0]["balance_fen"] == "82590"
    filtered_page = journal(ledger, account_id=bank, kind="expense", limit=1, offset=1)
    assert filtered_page["items"][0]["id"] == expense["id"]
    assert filtered_page["items"][0]["cash_effects"][0]["balance_fen"] == "98770"
    assert ledger[0].metadata() == before
    updated = send(
        ledger,
        "/events/" + expense["id"],
        {
            "kind": "expense",
            "account_id": bank,
            "amount_fen": "1000",
            "effective_date": "2026-01-10",
            "category_id": next(
                c["id"] for c in ledger[1].get("/api/v1/categories").json() if c["name"] == "餐饮"
            ),
            "revision": 1,
        },
        "PUT",
    )
    assert updated.status_code == 200, updated.text
    assert effects(ledger, last["id"])[0]["balance_fen"] == "82820"
    assert send(ledger, "/events/" + last["id"] + "/void", {"revision": 1}).status_code == 200
    assert effects(ledger, last["id"]) == []
    assert (
        effects(ledger, bought.json()["id"], include_investments=True)[0]["balance_fen"] == "83020"
    )


def test_native_debt_receivable_balances_and_integer_precision(ledger):
    bank = account(ledger, "Synthetic bank", "100000")
    debt = account(ledger, "Synthetic debt", "0", "liability")
    receivable = account(ledger, "Synthetic receivable", "0", "receivable")
    borrowed = event(
        ledger,
        debt,
        "1000",
        "transfer",
        target_account_id=bank,
        fee_fen="10",
        category_id=next(
            c["id"] for c in ledger[1].get("/api/v1/categories").json() if c["name"] == "手续费"
        ),
    )
    repaid = event(ledger, bank, "400", "transfer", target_account_id=debt)
    lent = event(ledger, bank, "300", "transfer", target_account_id=receivable)
    returned = event(ledger, receivable, "100", "transfer", target_account_id=bank)
    assert effects(ledger, borrowed["id"], account_id=debt)[0]["balance_fen"] == "1000"
    native = effects(ledger, repaid["id"], account_id=debt)[0]
    assert (native["delta_fen"], native["balance_fen"], native["account_kind"]) == (
        "-400",
        "600",
        "liability",
    )
    assert effects(ledger, lent["id"], account_id=receivable)[0]["balance_fen"] == "300"
    native = effects(ledger, returned["id"], account_id=receivable)[0]
    assert (native["delta_fen"], native["balance_fen"], native["account_kind"]) == (
        "-100",
        "200",
        "receivable",
    )
    large = account(ledger, "Synthetic large", "1000000000000")
    small = event(ledger, large, "1")
    assert effects(ledger, small["id"])[0]["balance_fen"] == "999999999999"
