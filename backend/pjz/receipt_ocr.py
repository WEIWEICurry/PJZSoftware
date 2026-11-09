"""Local OCR and conservative parsing for confirmed fund buy receipts."""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
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
    confirmation_date: str | None
    nav_date: str | None
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
    purchase = _day(_field(lines, "买入时间", "申购时间"))
    confirmation = _day(_field(lines, "确认时间", "确认日期"))
    nav_date = _day(_field(lines, "成交净值所属日", "净值所属日", "净值日期"))
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
    if not nav_date:
        warnings.append("请根据回执补填成交净值所属日。")
    if not any((product, code, amount, quantity, confirmation)):
        raise RuleError("OCR_UNSUPPORTED_RECEIPT")

    return ReceiptPreview(
        product=product[:200] if product else None,
        code=code if code and re.fullmatch(r"[0-9]{6}", code) else None,
        payment_hint=re.sub(r"[0-9]{5,}", "…", payment)[:80] if payment else None,
        amount=amount if amount and Decimal(amount) > 0 else None,
        fee=fee,
        confirmed_amount=confirmed,
        quantity=quantity if quantity and Decimal(quantity) > 0 else None,
        unit_nav=_number(_field(lines, "确认净值"), 8, "元"),
        purchase_date=purchase,
        confirmation_date=confirmation,
        nav_date=nav_date,
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
