"""Versioned read-only reports and optional budget commands."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator

from pjz.budgets import Budgets
from pjz.daily_api import CreatedOutput, Fen, Key, StrictInput
from pjz.domain import MAX_FEN
from pjz.reports import Reports

Period = Literal["day", "week", "month", "year"]
Month = str


class CategoryReport(BaseModel):
    category_id: str
    category_name: str
    direction: Literal["income", "expense"]
    amount_fen: str | None
    known_fen: str
    historical_fen: str
    detail_fen: str
    share_bps: int | None


class ReportTotals(BaseModel):
    start: str
    end: str
    income_fen: str | None
    expense_fen: str | None
    surplus_fen: str | None
    known_income_fen: str
    known_expense_fen: str
    daily_expense_fen: str | None
    day_count: int
    covered_count: int
    detail_count: int
    historical_count: int
    categories: list[CategoryReport]


class TrendPoint(BaseModel):
    start: str
    end: str
    income_fen: str | None
    expense_fen: str | None
    surplus_fen: str | None
    known_income_fen: str
    known_expense_fen: str
    status: Literal["recorded", "unallocated", "future"]


class ReportChange(BaseModel):
    metric: Literal["income", "expense", "surplus"]
    delta_fen: str | None
    change_bps: str | None


class ReportHistory(BaseModel):
    start: str
    end: str
    category_name: str
    direction: Literal["income", "expense"]
    source: str
    amount_fen: str
    allocated: bool


class ReportOutput(BaseModel):
    period: Period
    calendar_end: str
    current: ReportTotals
    previous: ReportTotals | None
    changes: list[ReportChange]
    trend: list[TrendPoint]
    history_ranges: list[ReportHistory]


class ReportEntry(BaseModel):
    id: str
    start: str
    end: str
    direction: Literal["income", "expense"]
    category_id: str
    category_name: str
    account_name: str
    note: str
    source: str
    amount_fen: str
    counted_fen: str | None
    status: Literal["included", "covered", "unallocated"]


class ReportEntryPage(BaseModel):
    items: list[ReportEntry]
    total: int


class BudgetOutput(BaseModel):
    id: str
    month: str
    category_id: str
    category_name: str
    revision: int
    limit_fen: str | None
    used_fen: str | None
    net_expense_fen: str | None
    remaining_fen: str | None
    over_fen: str | None
    used_bps: str | None
    status: Literal["unset", "future", "unknown", "over", "exhausted", "near", "normal"]


class BudgetPage(BaseModel):
    month: str
    ledger_revision: int
    as_of: str
    items: list[BudgetOutput]


class BudgetInput(StrictInput):
    limit_fen: Fen | None
    revision: int = Field(ge=0, strict=True)

    @field_validator("limit_fen")
    @classmethod
    def positive_limit(cls, value: str | None) -> str | None:
        if value is not None and not 0 < int(value) <= MAX_FEN:
            raise ValueError("Positive budget required")
        return value


class CopyInput(StrictInput):
    ledger_revision: int = Field(ge=1, strict=True)


class CopiedOutput(BaseModel):
    copied: int


def report_router(reports: Reports, budgets: Budgets) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/reports", response_model=ReportOutput)
    def report(period: Period, anchor: date) -> dict[str, Any]:
        return reports.get(period, anchor)

    @router.get("/reports/entries", response_model=ReportEntryPage)
    def entries(
        period: Period,
        anchor: date,
        category_id: UUID | None = None,
        direction: Literal["income", "expense"] | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return reports.entries(
            period, anchor, str(category_id) if category_id else None, direction, offset, limit
        )

    @router.get("/reports/export")
    def export(
        period: Period,
        anchor: date,
        category_id: UUID | None = None,
        direction: Literal["income", "expense"] | None = None,
    ) -> Response:
        payload = reports.export(
            period, anchor, str(category_id) if category_id else None, direction
        )
        return Response(
            payload,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="'
                + f'pjz-{period}-{anchor.isoformat()}.csv"'
            },
        )

    @router.get("/budgets/{month}", response_model=BudgetPage)
    def budget_page(month: Month) -> dict[str, Any]:
        return budgets.get(month)

    @router.put("/budgets/{month}/{category_id}", response_model=CreatedOutput)
    def save_budget(month: Month, category_id: UUID, body: BudgetInput, key: Key) -> dict[str, Any]:
        return budgets.save(month, str(category_id), body.limit_fen, body.revision, key)

    @router.post("/budgets/{month}/copy-previous", response_model=CopiedOutput)
    def copy_budgets(month: Month, body: CopyInput, key: Key) -> dict[str, Any]:
        return budgets.copy_previous(month, body.ledger_revision, key)

    return router
