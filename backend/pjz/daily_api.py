"""Versioned daily-ledger API with string amounts and typed OpenAPI responses."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pjz.account_deletion import AccountDeletion
from pjz.accounting import Accounting
from pjz.domain import MAX_FEN, RuleError

AccountKind = Literal["cash", "bank", "payment", "securities", "liability", "receivable"]
EventKind = Literal["income", "expense", "refund", "transfer", "adjustment"]
Fen = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]{0,12})$")]
Key = Annotated[
    str, Header(alias="Idempotency-Key", min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedInput(StrictInput):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name required")
        return value


class AccountInput(NamedInput):
    kind: AccountKind
    opening_date: date
    opening_fen: Fen = "0"

    @field_validator("opening_date")
    @classmethod
    def past_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Future date")
        return value

    @field_validator("opening_fen")
    @classmethod
    def opening_amount(cls, value: str) -> str:
        if not 0 <= int(value) <= MAX_FEN:
            raise ValueError("Out of range")
        return value


class AccountChange(NamedInput):
    revision: int = Field(ge=1, strict=True)
    archived: bool = Field(strict=True)


class CategoryInput(NamedInput):
    direction: Literal["income", "expense"]


class EventInput(StrictInput):
    kind: EventKind
    effective_date: date
    account_id: UUID
    amount_fen: Fen
    target_account_id: UUID | None = None
    category_id: UUID | None = None
    original_event_id: UUID | None = None
    fee_fen: Fen = "0"
    note: str = Field(default="", max_length=500)

    @field_validator("effective_date")
    @classmethod
    def past_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Future date")
        return value

    @field_validator("amount_fen", "fee_fen")
    @classmethod
    def bounded_amount(cls, value: str) -> str:
        if abs(int(value)) > MAX_FEN:
            raise ValueError("Out of range")
        return value

    @field_validator("fee_fen")
    @classmethod
    def nonnegative_fee(cls, value: str) -> str:
        if int(value) < 0:
            raise ValueError("Negative fee")
        return value


class LoanInput(StrictInput):
    action: Literal["borrow", "repay", "lend", "collect"]
    cash_account_id: UUID
    counterparty_id: UUID | None = None
    counterparty_name: str | None = Field(default=None, min_length=1, max_length=50)
    effective_date: date
    amount_fen: Fen
    note: str = Field(default="", max_length=500)

    @field_validator("effective_date")
    @classmethod
    def past_date(cls, value: date) -> date:
        return EventInput.past_date(value)

    @field_validator("amount_fen")
    @classmethod
    def principal(cls, value: str) -> str:
        if not 0 < int(value) <= MAX_FEN:
            raise ValueError("Positive principal required")
        return value


class RevisionInput(StrictInput):
    revision: int = Field(ge=1, strict=True)


class EventChange(EventInput):
    revision: int = Field(ge=1, strict=True)


class AccountOutput(BaseModel):
    id: str
    name: str
    kind: AccountKind
    opening_date: str
    balance_fen: str
    archived: bool
    revision: int


class CategoryOutput(BaseModel):
    id: str
    name: str
    direction: Literal["income", "expense"]


class EventOutput(BaseModel):
    id: str
    kind: str
    effective_date: str
    account_id: str
    target_account_id: str | None
    category_id: str | None
    original_event_id: str | None
    amount_fen: str
    fee_fen: str
    note: str
    status: Literal["active", "void"]
    revision: int


class EventPage(BaseModel):
    items: list[EventOutput]
    total: int


class SummaryOutput(BaseModel):
    income_fen: str
    expense_fen: str
    surplus_fen: str
    assets_fen: str
    receivable_fen: str
    debt_fen: str
    net_fen: str


class CreatedOutput(BaseModel):
    id: str


class DeleteConfirmation(StrictInput):
    preview_token: str = Field(min_length=20, max_length=128)
    confirm_name: str = Field(min_length=1, max_length=60)


class DeleteImpact(BaseModel):
    account_id: str
    name: str
    before_fen: str
    after_fen: str


class DeletePreview(BaseModel):
    account_id: str
    account_name: str
    event_count: int
    refund_count: int
    transfer_count: int
    other_accounts: list[DeleteImpact]
    preview_token: str
    can_delete: bool
    reason: str | None


class DeleteOutput(BaseModel):
    deleted: bool
    event_count: int
    backup_path: str


class NoteSuggestion(BaseModel):
    note: str
    count: int


def router(service: Accounting, deletion: AccountDeletion) -> APIRouter:
    result = APIRouter(prefix="/api/v1")

    @result.get("/accounts", response_model=list[AccountOutput])
    def accounts() -> list[dict[str, Any]]:
        return service.accounts()

    @result.post("/accounts", response_model=CreatedOutput)
    def create_account(body: AccountInput, key: Key) -> dict[str, Any]:
        return service.create_account(body.model_dump(mode="json"), key)

    @result.patch("/accounts/{identifier}", response_model=CreatedOutput)
    def update_account(identifier: UUID, body: AccountChange, key: Key) -> dict[str, Any]:
        return service.update_account(str(identifier), body.model_dump(mode="json"), key)

    @result.post("/accounts/{identifier}/delete-preview", response_model=DeletePreview)
    def delete_preview(identifier: UUID) -> dict[str, Any]:
        return deletion.preview(str(identifier))

    @result.post("/accounts/{identifier}/delete", response_model=DeleteOutput)
    def delete_account(identifier: UUID, body: DeleteConfirmation, key: Key) -> dict[str, Any]:
        return deletion.commit(str(identifier), body.model_dump(), key)

    @result.get("/categories/{identifier}/note-suggestions", response_model=list[NoteSuggestion])
    def note_suggestions(identifier: UUID) -> list[dict[str, Any]]:
        return service.note_suggestions(str(identifier))

    @result.get("/categories", response_model=list[CategoryOutput])
    def categories() -> list[dict[str, Any]]:
        return service.categories()

    @result.post("/categories", response_model=CategoryOutput)
    def create_category(body: CategoryInput, key: Key) -> dict[str, Any]:
        return service.create_category(body.model_dump(mode="json"), key)

    @result.post("/loans", response_model=EventOutput)
    def record_loan(body: LoanInput, key: Key) -> dict[str, Any]:
        if body.counterparty_id and body.counterparty_name:
            raise RuleError("INVALID_EVENT_FIELDS")
        return service.record_loan(body.model_dump(mode="json"), key)

    @result.post("/events", response_model=EventOutput)
    def create_event(body: EventInput, key: Key) -> dict[str, Any]:
        return service.create_event(body.model_dump(mode="json"), key)

    @result.put("/events/{identifier}", response_model=EventOutput)
    def update_event(identifier: UUID, body: EventChange, key: Key) -> dict[str, Any]:
        return service.change_event(str(identifier), body.model_dump(mode="json"), key)

    @result.post("/events/{identifier}/void", response_model=EventOutput)
    def void_event(identifier: UUID, body: RevisionInput, key: Key) -> dict[str, Any]:
        return service.change_event(str(identifier), body.model_dump(), key, void=True)

    @result.get("/events", response_model=EventPage)
    def events(
        start: date,
        end: date,
        account_id: UUID | None = None,
        kind: Literal["opening", "income", "expense", "refund", "transfer", "adjustment"]
        | None = None,
        category_id: UUID | None = None,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if start > end:
            raise RuleError("INVALID_PERIOD")
        return service.events(
            start.isoformat(),
            end.isoformat(),
            str(account_id) if account_id else None,
            kind,
            str(category_id) if category_id else None,
            limit,
            offset,
        )

    @result.get("/summary", response_model=SummaryOutput)
    def summary(month: str = Query(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$")) -> dict[str, str]:
        year, number = (int(part) for part in month.split("-"))
        start = date(year, number, 1)
        end = date(year, number, calendar.monthrange(year, number)[1])
        return service.summary(start.isoformat(), end.isoformat())

    return result
