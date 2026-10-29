"""Synthetic opt-in networking and no-overwrite NAV acceptance."""

import json
import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest
from pjz.domain import RuleError
from pjz.fund_nav import fetch_nav
from test_daily_ledger import ledger as ledger
from test_daily_ledger import send
from test_investments import instrument, page, price


def query(ledger, asset, **extra):
    return send(
        ledger,
        "/fund-nav/preview",
        {
            "instrument_id": asset,
            "start": "2026-01-01",
            "end": "2026-01-31",
            "enabled": True,
            **extra,
        },
    )


def test_opt_in_preview_import_idempotency_and_no_overwrite(ledger, monkeypatch):
    mock = MagicMock(
        return_value=[
            {"price_date": "2026-01-20", "price": "1.23456789"},
            {"price_date": "2026-01-21", "price": "2"},
        ]
    )
    monkeypatch.setattr("pjz.fund_nav.fetch_nav", mock)
    asset = instrument(ledger, "000001", "fund", "FUND")
    assert query(ledger, asset, enabled=False).status_code == 422
    mock.assert_not_called()
    assert price(ledger, asset, "9", "2026-01-20").status_code == 200
    before = page(ledger)
    preview = query(ledger, asset).json()
    assert preview["rows"][0]["exists"]
    assert page(ledger) == before
    token = preview["token"]
    key = str(uuid.uuid4())
    result = send(ledger, "/fund-nav/import", {"token": token}, key=key)
    assert result.json() == {"imported": 1, "skipped": 1}
    assert send(ledger, "/fund-nav/import", {"token": token}, key=key).json() == result.json()
    assert (
        next(v for v in page(ledger)["valuations"] if v["price_date"] == "2026-01-20")["price"]
        == "9"
    )
    assert send(ledger, "/fund-nav/import", {"token": "fake"}).status_code == 422
    assert send(ledger, "/fund-nav/import", {"token": token}).json() == {
        "imported": 0,
        "skipped": 2,
    }


def test_nonfund_and_invalid_range_never_request(ledger, monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("pjz.fund_nav.fetch_nav", mock)
    asset = instrument(ledger)
    assert query(ledger, asset).status_code == 422
    assert query(ledger, asset, start="2025-01-01").status_code == 422
    assert query(ledger, asset, start="2026-02-01").status_code == 422
    mock.assert_not_called()


@pytest.mark.parametrize(
    "row",
    [
        {"FSRQ": "2026-01-20", "DWJZ": "NaN"},
        {"FSRQ": "2027-01-20", "DWJZ": "1"},
        {"FSRQ": "2026-01-20", "DWJZ": "0"},
    ],
)
def test_invalid_remote_data(row, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"ErrCode": 0, "TotalCount": 1, "Data": {"LSJZList": [row]}}
    ).encode()
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("pjz.fund_nav.urllib.request.build_opener", lambda *a: opener)
    with pytest.raises(RuleError, match="NAV_SOURCE_UNAVAILABLE"):
        fetch_nav("000001", date(2026, 1, 1), date(2026, 1, 31))


def test_exact_remote_json_and_timeout(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        b'{"ErrCode":0,"TotalCount":1,"Data":{"LSJZList":'
        b'[{"FSRQ":"2026-01-20","DWJZ":"1.23456789"}]}}'
    )
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("pjz.fund_nav.urllib.request.build_opener", lambda *a: opener)
    assert fetch_nav("000001", date(2026, 1, 1), date(2026, 1, 31)) == [
        {"price_date": "2026-01-20", "price": "1.23456789"}
    ]
    opener.open.side_effect = TimeoutError()
    with pytest.raises(RuleError):
        fetch_nav("000001", date(2026, 1, 1), date(2026, 1, 31))


@pytest.mark.parametrize(
    "payload",
    [b"x" * 1000001, b"{}", b'{"ErrCode":0,"TotalCount":2,"Data":{"LSJZList":[]}}'],
    ids=["oversize", "missing", "truncated"],
)
def test_bad_or_excess_remote_response(payload, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = payload
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("pjz.fund_nav.urllib.request.build_opener", lambda *a: opener)
    with pytest.raises(RuleError):
        fetch_nav("000001", date(2026, 1, 1), date(2026, 1, 31))


def test_expired_preview_and_void_price_protected(ledger, monkeypatch):
    asset = instrument(ledger, "000001", "fund", "FUND")
    assert price(ledger, asset, "9", "2026-01-20").status_code == 200
    assert price(ledger, asset, "9", "2026-01-20", revision=1, status="void").status_code == 200
    monkeypatch.setattr(
        "pjz.fund_nav.fetch_nav", lambda *a: [{"price_date": "2026-01-20", "price": "1"}]
    )
    token = query(ledger, asset).json()["token"]
    assert send(ledger, "/fund-nav/import", {"token": token}).json() == {
        "imported": 0,
        "skipped": 1,
    }
    monkeypatch.setattr("pjz.fund_nav.time.monotonic", lambda: 99999999999)
    assert send(ledger, "/fund-nav/import", {"token": token}).status_code == 422


def test_remote_pagination_preserves_all_rows(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.side_effect = [
        json.dumps(
            {
                "ErrCode": 0,
                "TotalCount": 2,
                "Data": {"LSJZList": [{"FSRQ": "2026-01-20", "DWJZ": "1"}]},
            }
        ).encode(),
        json.dumps(
            {
                "ErrCode": 0,
                "TotalCount": 2,
                "Data": {"LSJZList": [{"FSRQ": "2026-01-21", "DWJZ": "2"}]},
            }
        ).encode(),
    ]
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("pjz.fund_nav.urllib.request.build_opener", lambda *a: opener)
    assert len(fetch_nav("000001", date(2026, 1, 1), date(2026, 1, 31))) == 2
    assert opener.open.call_count == 2
