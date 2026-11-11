"""Local OCR and conservative parsing for confirmed fund buy receipts."""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pjz.domain import RuleError

if TYPE_CHECKING:
    from PIL.Image import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
_inference_lock = threading.Lock()


@dataclass(frozen=True)
class TextLine:
    text: str
    left: float
    center: float
    height: float
    score: float


@dataclass(frozen=True)
class ReceiptPreview:
    product: str | None
    code: str | None
    payment_hint: str | None
    amount: str | None
    fee: str | None
    confirmed_amount: str | None
    quantity: str | None
    unit_nav: str | None
    purchase_date: str | None
    purchase_time: str | None
    confirmation_date: str | None
    nav_date: str | None
    nav_date_estimated: bool
    warnings: list[str]


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _field(lines: Sequence[TextLine], *labels: str) -> str | None:
    for label in labels:
        for line in lines:
            if line.score < 0.85 or not line.text.startswith(label):
                continue
            inline = line.text[len(label) :].lstrip(" :")
            if inline:
                return inline
            right = sorted(
                (
                    other
                    for other in lines
                    if other.left > line.left
                    and other.score >= 0.85
                    and abs(other.center - line.center) <= 0.6 * line.height
                ),
                key=lambda item: item.left,
            )
            if right:
                return " ".join(item.text for item in right)
    return None


def _number(value: str | None, scale: int, unit: str = "") -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", "", value).removeprefix("¥").removesuffix(unit)
    match = re.fullmatch(
        rf"(?:[0-9]{{1,12}}|[0-9]{{1,3}}(?:,[0-9]{{3}}){{1,3}})"
        rf"(?:\.[0-9]{{1,{scale}}})?",
        text,
    )
    if not match:
        return None
    return format(Decimal(text.replace(",", "")), "f")


def _day(value: str | None) -> str | None:
    match = re.fullmatch(
        r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
        (value or "").strip(),
    )
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError:
        return None


# 2026 SSE holiday notice, with weekend closures handled separately.
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
_CLOSED_2026 = (
    ("01-01", "01-03"),
    ("02-15", "02-23"),
    ("04-04", "04-06"),
    ("05-01", "05-05"),
    ("06-19", "06-21"),
    ("09-25", "09-27"),
    ("10-01", "10-07"),
)


def _purchase(value: str | None) -> tuple[str | None, time | None]:
    text = (value or "").strip()
    match = re.fullmatch(
        r"(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*"
        r"(\d{2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?",
        text,
    )
    if not match:
        return _day(text), None
    day, hour, minute, second = match.groups()
    try:
        return _day(day), time(int(hour), int(minute), int(second or "0"))
    except ValueError:
        return _day(day), None


def _estimated_nav_date(purchase: str, purchase_time: time, confirmation: str) -> str | None:
    day = date.fromisoformat(purchase)
    if day.year != 2026:
        return None
    latest = date.fromisoformat(confirmation)
    if purchase_time >= time(15):
        day += timedelta(days=1)
    while day.year == 2026 and day <= latest:
        month_day = day.isoformat()[5:]
        if day.weekday() < 5 and not any(start <= month_day <= end for start, end in _CLOSED_2026):
            return day.isoformat()
        day += timedelta(days=1)
    return None


def parse_receipt(raw_lines: Sequence[TextLine]) -> ReceiptPreview:
    lines = [
        TextLine(_text(line.text), line.left, line.center, line.height, line.score)
        for line in raw_lines
    ]
    if not any(
        line.score >= 0.85 and re.sub(r"\s+", "", line.text) in {"买入成功", "申购成功"}
        for line in lines
    ):
        raise RuleError("OCR_UNSUPPORTED_RECEIPT")

    amount = _number(_field(lines, "买入金额", "申购金额"), 2, "元")
    fee = _number(_field(lines, "手续费", "申购费"), 2, "元")
    confirmed = _number(_field(lines, "确认金额"), 2, "元")
    quantity = _number(_field(lines, "确认份额"), 8, "份")
    purchase, purchase_time = _purchase(_field(lines, "买入时间", "申购时间"))
    confirmation = _day(_field(lines, "确认时间", "确认日期"))
    nav_date_text = _field(lines, "成交净值所属日", "净值所属日", "净值日期")
    nav_date = _day(nav_date_text)
    nav_date_estimated = False
    product = _field(lines, "买入产品", "申购产品", "基金名称")
    code = _field(lines, "基金代码", "产品代码")
    payment = _field(lines, "付款方式", "支付方式")
    warnings = []
    if amount is not None and fee is not None and confirmed is not None:
        if Decimal(amount) != Decimal(fee) + Decimal(confirmed):
            warnings.append("买入金额与确认金额加手续费不一致，请对照原图。")
    if purchase and confirmation and purchase > confirmation:
        warnings.append("买入日期晚于确认日期，请核对。")
    if nav_date and confirmation and nav_date > confirmation:
        warnings.append("净值所属日晚于确认日期，请重新填写。")
        nav_date = None
    if not nav_date_text and purchase and purchase_time is not None and confirmation:
        nav_date = _estimated_nav_date(purchase, purchase_time, confirmation)
        nav_date_estimated = nav_date is not None
    if nav_date_estimated:
        warnings.append("净值所属日按买入时间和沪深开市日推算，请以实际回执为准。")
    elif not nav_date:
        warnings.append("请根据回执补填成交净值所属日。")
    if not any((product, code, amount, quantity, confirmation)):
        raise RuleError("OCR_UNSUPPORTED_RECEIPT")

    return ReceiptPreview(
        product=product.rstrip(" >›»❯→")[:200] or None if product else None,
        code=code if code and re.fullmatch(r"[0-9]{6}", code) else None,
        payment_hint=re.sub(r"[0-9]{5,}", "…", payment)[:80] if payment else None,
        amount=amount if amount and Decimal(amount) > 0 else None,
        fee=fee,
        confirmed_amount=confirmed,
        quantity=quantity if quantity and Decimal(quantity) > 0 else None,
        unit_nav=_number(_field(lines, "确认净值"), 8, "元"),
        purchase_date=purchase,
        purchase_time=purchase_time.isoformat() if purchase_time is not None else None,
        confirmation_date=confirmation,
        nav_date=nav_date,
        nav_date_estimated=nav_date_estimated,
        warnings=warnings,
    )


@lru_cache(maxsize=1)
def _engine() -> Callable[[Image], Any]:
    import rapidocr

    directory = Path(rapidocr.__file__).resolve().parent / "models"
    detection = directory / "PP-OCRv6_det_small.onnx"
    recognition = directory / "PP-OCRv6_rec_small.onnx"
    if not detection.is_file() or not recognition.is_file():
        raise RuleError("OCR_UNAVAILABLE")
    return rapidocr.RapidOCR(
        params={
            "Det.model_path": str(detection),
            "Rec.model_path": str(recognition),
            "Global.use_cls": False,
            "Global.log_level": "critical",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        },
    )


def recognize_lines(payload: bytes) -> list[TextLine]:
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise RuleError("OCR_INVALID_IMAGE")
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(payload), formats=["PNG", "JPEG"]) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise RuleError("OCR_INVALID_IMAGE")
            pixels = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise RuleError("OCR_INVALID_IMAGE") from None

    try:
        with _inference_lock:
            result = _engine()(pixels)
        if result.boxes is None or result.txts is None or result.scores is None:
            return []
        lines = []
        for box, text, score in zip(result.boxes, result.txts, result.scores, strict=True):
            top = float(min(point[1] for point in box))
            bottom = float(max(point[1] for point in box))
            lines.append(
                TextLine(
                    text,
                    float(min(point[0] for point in box)),
                    (top + bottom) / 2,
                    bottom - top,
                    float(score),
                )
            )
        return lines
    except RuleError:
        raise
    except Exception:
        raise RuleError("OCR_UNAVAILABLE") from None


@dataclass(frozen=True)
class HoldingPreview:
    product: str | None
    code: str | None
    quantity: str | None
    amount: str | None
    pending: str | None
    unit_nav: str | None
    nav_date: str | None
    nav_month_day: str | None
    cost_price: str | None
    warnings: list[str]


def parse_holding(raw_lines: Sequence[TextLine]) -> HoldingPreview:
    lines = [
        TextLine(_text(line.text), line.left, line.center, line.height, line.score)
        for line in raw_lines
        if line.score >= 0.85
    ]
    titles = [line for line in lines if line.text == "资产详情"]
    if not titles:
        raise RuleError("OCR_UNSUPPORTED_HOLDING")
    codes = [line for line in lines if re.fullmatch(r"[0-9]{6}", line.text)]
    code_line = codes[0] if len(codes) == 1 else None
    product = None
    if code_line:
        heading = sorted(
            (
                line
                for line in lines
                if titles[0].center + titles[0].height
                < line.center
                < code_line.center - code_line.height * 0.5
            ),
            key=lambda line: (line.center, line.left),
        )
        product = "".join(line.text for line in heading)[:200] or None
    labels = ("持有金额", "待确认金额", "持仓成本价", "持有份额", "基金净值", "日涨幅")

    def field(label: str) -> str | None:
        for line in lines:
            if not line.text.startswith(label):
                continue
            value = line.text[len(label) :].lstrip(" :")
            if value:
                return value
            right = sorted(
                (
                    other
                    for other in lines
                    if other.left > line.left
                    and abs(other.center - line.center) <= 0.6 * line.height
                ),
                key=lambda other: other.left,
            )
            parts = []
            for other in right:
                if any(other.text.startswith(name) for name in labels):
                    break
                parts.append(other.text)
            return " ".join(parts) or None
        return None

    nav_text = re.sub(r"\s+", "", field("基金净值") or "")
    nav_match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]{1,8})?)(?:元)?(?:[（(]([0-9]{4}-)?([0-9]{1,2})-([0-9]{1,2})[)）])?",
        nav_text,
    )
    nav = _number(nav_match[1], 8) if nav_match else None
    nav_date = None
    month_day = None
    if nav_match and nav_match[3]:
        year = int((nav_match[2] or "2000-")[:-1])
        try:
            parsed = date(year, int(nav_match[3]), int(nav_match[4]))
            if nav_match[2]:
                nav_date = parsed.isoformat()
            else:
                month_day = parsed.strftime("%m-%d")
        except ValueError:
            pass
    quantity = _number(field("持有份额"), 8, "份")
    amount = _number(field("持有金额"), 2, "元")
    if quantity is None and amount is None:
        raise RuleError("OCR_UNSUPPORTED_HOLDING")
    warnings = []
    if month_day:
        warnings.append("净值日期仅含月日，请按截图持仓日期核对推定年份。")
    if not nav_date and not month_day:
        warnings.append("净值日期未识别，请人工填写。")
    return HoldingPreview(
        product,
        code_line.text if code_line else None,
        quantity,
        amount,
        _number(field("待确认金额"), 2, "元"),
        nav,
        nav_date,
        month_day,
        _number(field("持仓成本价"), 8, "元"),
        warnings,
    )
