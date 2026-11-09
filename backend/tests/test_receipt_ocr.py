from dataclasses import asdict

import pytest
from pjz.domain import RuleError
from pjz.receipt_ocr import TextLine, parse_receipt, recognize_lines
from test_daily_ledger import ledger as ledger


def lines(*rows):
    return [
        TextLine(text, 20.0 + column * 180, 20.0 + row * 30, 18.0, 0.99)
        for row, parts in enumerate(rows)
        for column, text in enumerate(parts)
    ]


def test_receipt_reads_label_value_pairs_and_distinct_dates():
    result = parse_receipt(
        lines(
            ("买入成功",),
            ("999.00元",),
            ("买入产品", "合成测试基金A"),
            ("买入金额", "100.00元"),
            ("买入时间", "2026-11-03", "14:01:13"),
            ("确认金额", "99.88元"),
            ("确认份额", "93.08000001份"),
            ("确认净值", "1.0730"),
            ("手续费", "0.12元"),
            ("确认时间", "2026-11-04"),
            ("订单号", "111222333444555"),
        )
    )
    assert (result.amount, result.fee, result.confirmed_amount) == ("100.00", "0.12", "99.88")
    assert result.quantity == "93.08000001"
    assert result.product == "合成测试基金A"
    assert result.purchase_date == "2026-11-03"
    assert result.confirmation_date == "2026-11-04"
    assert result.unit_nav == "1.0730" and result.nav_date is None
    assert "111222333444555" not in str(asdict(result))


def test_partial_receipt_keeps_missing_values_and_flags_conflicts():
    result = parse_receipt(
        lines(
            ("申购成功",),
            ("买入金额 100.00元",),
            ("手续费 0.12元",),
            ("确认金额 99.86元",),
            ("确认时间", "2026-11-04"),
            ("净值所属日", "2026-11-05"),
        )
        + [TextLine("确认份额 9.99份", 20, 240, 18, 0.53)]
    )
    assert result.quantity is None and result.nav_date is None
    assert any("不一致" in warning for warning in result.warnings)
    assert any("晚于" in warning for warning in result.warnings)
    with pytest.raises(RuleError, match="OCR_UNSUPPORTED_RECEIPT"):
        parse_receipt(lines(("确认中",), ("买入金额", "10元")))
    with pytest.raises(RuleError, match="OCR_INVALID_IMAGE"):
        recognize_lines(b"not an image")


def test_authenticated_preview_does_not_save_a_trade(ledger, monkeypatch):
    store, client, headers = ledger
    monkeypatch.setattr(
        "pjz.investment_api.recognize_lines",
        lambda _: lines(("买入成功",), ("买入金额", "10.00元"), ("确认份额", "9.2份")),
    )
    before = store.metadata()
    path = "/api/v1/investments/receipt-preview"
    files = {"file": ("synthetic.png", b"mock", "image/png")}
    assert client.post(path, files=files, headers={"Origin": headers["Origin"]}).status_code == 403
    response = client.post(path, files=files, headers=headers)
    assert response.status_code == 200
    assert response.json()["amount"] == "10.00"
    assert store.metadata() == before
    assert client.get("/api/v1/investments").json()["trades"] == []
