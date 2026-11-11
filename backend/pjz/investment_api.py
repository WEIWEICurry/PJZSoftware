"""Local authenticated investment endpoints; exact decimal strings on the wire."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pjz.daily_api import (
    CreatedOutput,
    EventInput,
    Fen,
    Key,
    NamedInput,
    RevisionInput,
    StrictInput,
)
from pjz.domain import RuleError
from pjz.holdings_reconciliation import reconcile
from pjz.investment_domain import decimal_value
from pjz.investment_todos import InvestmentTodos, investment_todos
from pjz.investments import Investments
from pjz.receipt_ocr import (
    MAX_IMAGE_BYTES,
    HoldingPreview,
    ReceiptPreview,
    parse_holding,
    parse_receipt,
    recognize_lines,
)

InvestmentAction = Literal["opening", "buy", "sell", "cash_dividend", "reinvest", "split"]


class InstrumentInput(NamedInput):
    market: Literal["SH", "SZ", "BJ", "FUND"]
    code: str = Field(pattern=r"^[0-9]{6}$")
    kind: Literal["stock", "etf", "fund"]


class InstrumentOutput(InstrumentInput):
    model_config = ConfigDict(extra="ignore")
    id: str
    revision: int


class TradeInput(StrictInput):
    account_id: UUID
    instrument_id: UUID
    action: InvestmentAction
    effective_date: date
    nav_date: date | None = None
    quantity: str = Field(max_length=21)
    amount_fen: Fen = "0"
    costs_fen: Fen = "0"
    cost_basis_fen: Fen | None = None
    amount_mode: Literal["gross", "net"] = "gross"
    note: str = Field(default="", max_length=500)
    cash_account_id: UUID | None = None
    split_from_quantity: str | None = Field(default=None, max_length=21)

    @field_validator("effective_date")
    @classmethod
    def past(cls, value: date) -> date:
        return EventInput.past_date(value)

    @field_validator("quantity")
    @classmethod
    def units(cls, value: str) -> str:
        if value != "0":
            decimal_value(value)
        return value

    @model_validator(mode="after")
    def event_fields(self) -> TradeInput:
        if (self.action == "cash_dividend") != (self.quantity == "0"):
            raise ValueError("Dividend has no units; other events require positive units")
        if self.cash_account_id and self.action not in ("buy", "sell", "cash_dividend", "reinvest"):
            raise ValueError("Only cash-changing trades have a payment account")
        if self.action == "split":
            if not self.split_from_quantity or not self.note.strip():
                raise ValueError("Confirmed old units and evidence required")
            decimal_value(self.split_from_quantity)
        elif self.split_from_quantity is not None:
            raise ValueError("Old units only apply to a unit conversion")
        if self.action not in ("buy", "sell") and self.amount_mode != "gross":
            raise ValueError("Net amount mode only applies to purchases and sales")
        if self.action in ("buy", "sell"):
            if self.nav_date and self.nav_date > self.effective_date:
                raise ValueError("NAV date must not be after confirmation date")
        elif self.nav_date is not None:
            raise ValueError("NAV date only applies to purchases and sales")
        return self

    @field_validator("amount_fen", "costs_fen", "cost_basis_fen")
    @classmethod
    def amount(cls, value: str | None) -> str | None:
        if value is not None:
            EventInput.bounded_amount(value)
            EventInput.nonnegative_fee(value)
        return value


class ReceiptTradeInput(TradeInput):
    action: Literal["buy"] = "buy"
    amount_mode: Literal["net"] = "net"
    nav_date: date
    cash_account_id: UUID
    costs_fen: Fen
    allow_possible_duplicate: bool = Field(default=False, strict=True)


class ReceiptBatchInput(StrictInput):
    rows: list[ReceiptTradeInput] = Field(min_length=1, max_length=20)


class ReceiptBatchOutput(BaseModel):
    ids: list[str]


class TradeChange(TradeInput):
    revision: int = Field(ge=1, strict=True)


class TradeOutput(BaseModel):
    id: str
    account_id: str
    instrument_id: str
    action: InvestmentAction
    effective_date: str
    nav_date: str | None
    nav_date_source: str | None
    is_recurring: bool
    sequence: int
    quantity: str
    gross_fen: str
    costs_fen: str
    cost_basis_fen: str | None
    note: str
    status: Literal["active", "void"]
    revision: int
    cash_account_id: str | None
    split_from_quantity: str | None


class PriceInput(StrictInput):
    instrument_id: UUID
    price_date: date
    price: str = Field(max_length=21)
    revision: int = Field(default=0, ge=0, strict=True)
    status: Literal["active", "void"] = "active"

    @field_validator("price_date")
    @classmethod
    def past(cls, value: date) -> date:
        return EventInput.past_date(value)

    @field_validator("price")
    @classmethod
    def valid_price(cls, value: str) -> str:
        decimal_value(value)
        return value


class PriceOutput(PriceInput):
    source_label: str
    fetched_at: str | None
    model_config = ConfigDict(extra="ignore")
    id: str


class PositionOutput(BaseModel):
    account_id: str
    instrument_id: str
    quantity: str
    cost_fen: str | None
    realized_fen: str
    value_fen: str | None
    unrealized_fen: str | None
    share_bps: str | None
    holding_return_bps: str | None
    total_profit_fen: str | None
    total_return_bps: str | None
    price: str | None
    price_date: str | None
    cash_dividends_fen: str
    reinvested_dividends_fen: str
    valuation_required_from: str | None


class SellOption(BaseModel):
    instrument_id: str
    quantity: str


class InvestmentPage(BaseModel):
    instruments: list[InstrumentOutput]
    positions: list[PositionOutput]
    trades: list[TradeOutput]
    valuations: list[PriceOutput]
    known_value_fen: str
    missing_price_count: int
    unknown_cost_count: int
    realized_fen: str
    unrealized_fen: str | None
    total_profit_fen: str | None
    holding_return_bps: str | None
    total_return_bps: str | None
    known_net_fen: str
    net_fen: str | None
    cash_dividends_fen: str
    reinvested_dividends_fen: str


class HoldingRowInput(StrictInput):
    instrument_id: UUID
    quantity: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?$")
    amount_fen: Fen | None = None
    pending_fen: Fen | None = None
    unit_nav: str | None = Field(default=None, max_length=21)
    nav_date: date | None = None

    @field_validator("unit_nav")
    @classmethod
    def price(cls, value: str | None) -> str | None:
        if value is not None:
            decimal_value(value)
        return value

    @field_validator("amount_fen", "pending_fen")
    @classmethod
    def nonnegative(cls, value: str | None) -> str | None:
        return TradeInput.amount(value)


class HoldingComparisonInput(StrictInput):
    account_id: UUID
    as_of: date
    rows: list[HoldingRowInput] = Field(min_length=1, max_length=20)

    @field_validator("as_of")
    @classmethod
    def past(cls, value: date) -> date:
        return EventInput.past_date(value)

    @model_validator(mode="after")
    def dates(self) -> HoldingComparisonInput:
        if any(row.nav_date and row.nav_date > self.as_of for row in self.rows):
            raise ValueError("NAV date cannot exceed holdings observation date")
        return self


class HoldingComparisonRow(BaseModel):
    instrument_id: str
    name: str
    code: str
    platform_quantity: str
    local_quantity: str
    quantity_status: Literal["exact", "display", "different"]
    quantity_delta: str
    platform_value_fen: str | None
    pending_fen: str | None
    unit_nav: str | None
    nav_date: str | None
    reference_value_fen: str | None
    value_delta_fen: str | None
    local_value_fen: str | None
    local_price: str | None
    local_price_date: str | None
    local_cost_fen: str | None
    same_price_date: bool


class UnprovidedHolding(BaseModel):
    instrument_id: str
    name: str
    quantity: str


class HoldingComparisonOutput(BaseModel):
    revision: int
    as_of: str
    account_id: str
    rows: list[HoldingComparisonRow]
    unprovided: list[UnprovidedHolding]


def investment_router(service: Investments) -> APIRouter:
    router = APIRouter(prefix="/api/v1/investments")

    @router.get("", response_model=InvestmentPage)
    def page() -> object:
        return service.page()

    @router.get("/todos", response_model=InvestmentTodos)
    def todos() -> InvestmentTodos:
        return investment_todos(service)

    @router.post("/receipt-preview", response_model=ReceiptPreview)
    def receipt_preview(file: Annotated[UploadFile, File()]) -> ReceiptPreview:
        try:
            payload = file.file.read(MAX_IMAGE_BYTES + 1)
        finally:
            file.file.close()
        return parse_receipt(recognize_lines(payload))

    @router.post("/holding-preview", response_model=HoldingPreview)
    def holding_preview(file: Annotated[UploadFile, File()]) -> HoldingPreview:
        try:
            payload = file.file.read(MAX_IMAGE_BYTES + 1)
        finally:
            file.file.close()
        return parse_holding(recognize_lines(payload))

    @router.post("/holdings/reconcile", response_model=HoldingComparisonOutput)
    def holdings_reconcile(payload: HoldingComparisonInput) -> object:
        return reconcile(service, payload.model_dump(mode="json"))

    @router.post("/receipt-batches", response_model=ReceiptBatchOutput)
    def receipt_batch(payload: ReceiptBatchInput, key: Key) -> object:
        return service.receipt_batch(payload.model_dump(mode="json"), key)

    @router.get("/sell-options", response_model=list[SellOption])
    def sell_options(account_id: UUID, effective_date: date) -> object:
        if effective_date > date.today():
            raise RuleError("FUTURE_DATE")
        return service.sell_options(str(account_id), effective_date.isoformat())

    @router.post("/instruments", response_model=CreatedOutput)
    def instrument(payload: InstrumentInput, key: Key) -> object:
        return service.instrument(payload.model_dump(mode="json"), key)

    @router.post("/trades", response_model=CreatedOutput)
    def trade(payload: TradeInput, key: Key) -> object:
        return service.trade(payload.model_dump(mode="json"), key)

    @router.put("/trades/{identifier}", response_model=CreatedOutput)
    def change(identifier: UUID, payload: TradeChange, key: Key) -> object:
        return service.trade(payload.model_dump(mode="json"), key, str(identifier))

    @router.post("/trades/{identifier}/void", response_model=CreatedOutput)
    def void(identifier: UUID, payload: RevisionInput, key: Key) -> object:
        return service.void_trade(str(identifier), payload.revision, key)

    @router.put("/valuations", response_model=CreatedOutput)
    def price(payload: PriceInput, key: Key) -> object:
        return service.price(payload.model_dump(mode="json"), key)

    return router
