"""Typed authenticated read-only investment reporting endpoints."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from pjz.daily_api import AccountOutput
from pjz.investment_api import InstrumentOutput, TradeOutput
from pjz.investment_reports import InvestmentReports

InvestmentPeriod = Literal["month", "year", "custom"]
InvestmentKind = Literal["stock", "etf", "fund"]


class InvestmentPeriodTotals(BaseModel):
    record_count: int
    buy_outflow_fen: str
    sell_inflow_fen: str
    realized_fen: str
    cash_dividends_fen: str
    reinvested_dividends_fen: str
    fees_fen: str
    cash_delta_fen: str
    realized_and_dividends_fen: str


class InvestmentContribution(InvestmentPeriodTotals):
    instrument_id: str
    instrument_name: str
    market: str
    code: str
    kind: InvestmentKind


class InvestmentReportEntry(TradeOutput):
    account_name: str
    instrument_name: str
    market: str
    code: str
    kind: InvestmentKind
    cash_account_name: str
    cash_delta_fen: str | None
    allocated_cost_fen: str | None
    realized_fen: str | None


class InvestmentReportEntries(BaseModel):
    items: list[InvestmentReportEntry]
    total: int


class InvestmentAllocationGroup(BaseModel):
    group_by: Literal["instrument", "account", "kind"]
    id: str
    label: str
    value_fen: str | None
    known_value_fen: str
    missing_price_count: int
    position_count: int
    share_bps: str | None
    price_start: str | None
    price_end: str | None


class InvestmentCurrentAllocation(BaseModel):
    as_of_date: str
    total_value_fen: str | None
    known_value_fen: str
    missing_price_count: int
    selected_position_count: int
    groups: list[InvestmentAllocationGroup]


class InvestmentReportOutput(BaseModel):
    period: InvestmentPeriod
    start: str
    end: str
    requested_end: str
    ledger_revision: int
    totals: InvestmentPeriodTotals
    contributions: list[InvestmentContribution]
    current_allocation: InvestmentCurrentAllocation
    entries: InvestmentReportEntries
    accounts: list[AccountOutput]
    instruments: list[InstrumentOutput]


def report_query(
    period: InvestmentPeriod = "month",
    anchor: date | None = None,
    start: date | None = None,
    end: date | None = None,
    account_id: UUID | None = None,
    instrument_id: UUID | None = None,
    kind: InvestmentKind | None = None,
) -> dict[str, Any]:
    return {
        "period": period,
        "anchor": anchor or date.today(),
        "start": start,
        "end": end,
        "account_id": str(account_id) if account_id else None,
        "instrument_id": str(instrument_id) if instrument_id else None,
        "kind": kind,
    }


ReportQuery = Annotated[dict[str, Any], Depends(report_query)]


def investment_report_router(reports: InvestmentReports) -> APIRouter:
    router = APIRouter(prefix="/api/v1/investment-reports")

    @router.get("", response_model=InvestmentReportOutput)
    def report(
        query: ReportQuery, offset: int = Query(default=0, ge=0), include_void: bool = False
    ) -> dict[str, Any]:
        return reports.get(query, offset, include_void)

    @router.get(
        "/export",
        response_class=Response,
        responses={200: {"content": {"text/csv": {}}, "description": "UTF-8 BOM CSV"}},
    )
    def export(
        query: ReportQuery,
        dataset: Literal["report", "trades", "positions", "valuations"],
        include_void: bool = False,
    ) -> Response:
        return Response(
            reports.export(dataset, query, include_void),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="'
                + f'pjz-investment-{dataset}-{date.today()}.csv"'
            },
        )

    return router
