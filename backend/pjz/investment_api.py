"""Local authenticated investment endpoints; exact decimal strings on the wire."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pjz.daily_api import (
    CreatedOutput,
    EventInput,
    Fen,
    Key,
    NamedInput,
    RevisionInput,
    StrictInput,
)
from pjz.investment_domain import decimal_value
from pjz.investments import Investments


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
    action: Literal["opening", "buy", "sell"]
    effective_date: date
    quantity: str = Field(max_length=21)
    amount_fen: Fen = "0"
    costs_fen: Fen = "0"
    cost_basis_fen: Fen | None = None
    amount_mode: Literal["gross", "net"] = "gross"
    note: str = Field(default="", max_length=500)

    @field_validator("effective_date")
    @classmethod
    def past(cls, value: date) -> date:
        return EventInput.past_date(value)

    @field_validator("quantity")
    @classmethod
    def units(cls, value: str) -> str:
        decimal_value(value)
        return value

    @field_validator("amount_fen", "costs_fen", "cost_basis_fen")
    @classmethod
    def amount(cls, value: str | None) -> str | None:
        if value is not None:
            EventInput.bounded_amount(value)
            EventInput.nonnegative_fee(value)
        return value


class TradeChange(TradeInput):
    revision: int = Field(ge=1, strict=True)


class TradeOutput(BaseModel):
    id: str
    account_id: str
    instrument_id: str
    action: Literal["opening", "buy", "sell"]
    effective_date: str
    sequence: int
    quantity: str
    gross_fen: str
    costs_fen: str
    cost_basis_fen: str | None
    note: str
    status: Literal["active", "void"]
    revision: int


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
    price: str | None
    price_date: str | None


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
    known_net_fen: str
    net_fen: str | None


def investment_router(service: Investments) -> APIRouter:
    router = APIRouter(prefix="/api/v1/investments")

    @router.get("", response_model=InvestmentPage)
    def page() -> object:
        return service.page()

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
