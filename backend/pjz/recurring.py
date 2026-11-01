"Persistent recurring plans and atomic confirmation through existing investment writes."

from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from pjz.accounting import Accounting, fetch_all, now
from pjz.daily_api import EventInput, Fen, Key, StrictInput
from pjz.domain import RuleError
from pjz.investment_api import TradeInput
from pjz.investments import Investments
from pjz.recurring_domain import schedule


class PlanInput(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    account_id: UUID
    instrument_id: UUID
    start_date: date
    frequency: Literal["daily", "weekdays", "weekly"] = "weekdays"
    weekday: int = Field(default=0, ge=0, le=6)
    amount_fen: Fen
    costs_fen: Fen = "0"


class PlanOutput(PlanInput):
    model_config = ConfigDict(extra="ignore")
    id: str
    paused: bool
    revision: int


class PauseInput(StrictInput):
    revision: int = Field(ge=1, strict=True)
    paused: bool


class RangeInput(StrictInput):
    start: date
    end: date


class DraftOutput(BaseModel):
    id: str
    plan_id: str
    scheduled_date: str
    amount_fen: str
    costs_fen: str
    status: Literal["pending", "skipped", "confirmed"]
    revision: int
    event_id: str | None
    event_status: str | None
    effective_date: str | None
    quantity: str | None
    nav_date: str | None


class ReviewRow(StrictInput):
    id: UUID
    revision: int = Field(ge=1, strict=True)
    decision: Literal["confirm", "skip"]
    confirmation_date: date | None = None
    nav_date: date | None = None
    quantity: str = "0"
    amount_fen: Fen = "0"
    costs_fen: Fen = "0"


class ReviewInput(StrictInput):
    rows: list[ReviewRow] = Field(min_length=1, max_length=100)
    allow_possible_duplicate: bool = False


class CountOutput(BaseModel):
    count: int


def recurring_router(accounting: Accounting) -> APIRouter:
    router = APIRouter(prefix="/api/v1/recurring")
    investments = Investments(accounting)

    def plan(connection: Any, identifier: str) -> dict[str, Any]:
        found = fetch_all(
            connection, "SELECT * FROM investment_plans WHERE id=:id", {"id": identifier}
        )
        if not found:
            raise RuleError("RECURRING_NOT_FOUND")
        return found[0]

    def writable(connection: Any, item: dict[str, Any]) -> None:
        accounting.ensure_writable_accounts(connection, item)
        accounts = fetch_all(
            connection,
            "SELECT kind,opening_date FROM accounts WHERE id=:id",
            {"id": item["account_id"]},
        )
        assets = fetch_all(
            connection, "SELECT kind FROM instruments WHERE id=:id", {"id": item["instrument_id"]}
        )
        if (
            accounts[0]["kind"] in ("receivable", "liability")
            or not assets
            or assets[0]["kind"] != "fund"
        ):
            raise RuleError("RECURRING_FUND_CASH_REQUIRED")
        if item["start_date"] < accounts[0]["opening_date"]:
            raise RuleError("BEFORE_OPENING")

    @router.get("", response_model=list[PlanOutput])
    def plans() -> object:
        with accounting.engine.connect() as connection:
            rows = fetch_all(connection, "SELECT * FROM investment_plans ORDER BY created_at,id")
            return [
                {**r, "amount_fen": str(r["amount_fen"]), "costs_fen": str(r["costs_fen"])}
                for r in rows
            ]

    @router.post("", response_model=PlanOutput)
    def create(payload: PlanInput, key: Key) -> object:
        data = payload.model_dump(mode="json")

        def action(connection: Any) -> dict[str, Any]:
            writable(connection, data)
            if not data["name"].strip():
                raise RuleError("RECURRING_INVALID_PLAN")
            for name in ("amount_fen", "costs_fen"):
                EventInput.bounded_amount(data[name])
            if not 0 <= int(data["costs_fen"]) < int(data["amount_fen"]):
                raise RuleError("RECURRING_INVALID_PLAN")
            identifier = str(uuid4())
            connection.execute(
                text(
                    "INSERT INTO investment_plans (id,name,account_id,instrument_id,start"
                    "_date,frequency,weekday,amount_fen,costs_fen,created_at) VALUES (:id"
                    ",:name,:account_id,:instrument_id,:start_date,:frequency,:weekday,:a"
                    "mount,:costs,:at)"
                ),
                {
                    **data,
                    "id": identifier,
                    "amount": int(data["amount_fen"]),
                    "costs": int(data["costs_fen"]),
                    "at": now(),
                },
            )
            accounting.audit(connection, identifier, "create_recurring_plan", None, data)
            return {**data, "id": identifier, "paused": False, "revision": 1}

        return accounting.command(key, "create_recurring", data, action)

    @router.post("/{identifier}/pause", response_model=CountOutput)
    def pause(identifier: UUID, payload: PauseInput, key: Key) -> object:
        def action(connection: Any) -> dict[str, Any]:
            old = plan(connection, str(identifier))
            if old["revision"] != payload.revision:
                raise RuleError("REVISION_CONFLICT")
            connection.execute(
                text("UPDATE investment_plans SET paused=:paused,revision=revision+1 WHERE id=:id"),
                {"id": str(identifier), "paused": int(payload.paused)},
            )
            accounting.audit(
                connection, str(identifier), "pause_recurring_plan", old, payload.model_dump()
            )
            return {"count": 1}

        return accounting.command(
            key, "pause_recurring:" + str(identifier), payload.model_dump(), action
        )

    @router.post("/{identifier}/generate", response_model=CountOutput)
    def generate(identifier: UUID, payload: RangeInput, key: Key) -> object:
        def action(connection: Any) -> dict[str, Any]:
            item = plan(connection, str(identifier))
            writable(connection, item)
            if item["paused"]:
                raise RuleError("RECURRING_PAUSED")
            if payload.end > date.today():
                raise RuleError("FUTURE_DATE")
            days = schedule(
                payload.start,
                payload.end,
                date.fromisoformat(item["start_date"]),
                item["frequency"],
                item["weekday"],
            )
            count = 0
            for day in days:
                if fetch_all(
                    connection,
                    "SELECT id FROM investment_drafts WHERE plan_id=:id AND scheduled_date=:day",
                    {"id": str(identifier), "day": day},
                ):
                    continue
                connection.execute(
                    text(
                        "INSERT INTO investment_drafts "
                        "(id,plan_id,scheduled_date,amount_fen,costs_fen) VALUES "
                        "(:id,:plan,:day,:amount,:costs)"
                    ),
                    {
                        "id": str(uuid4()),
                        "plan": str(identifier),
                        "day": day,
                        "amount": item["amount_fen"],
                        "costs": item["costs_fen"],
                    },
                )
                count += 1
            accounting.audit(
                connection,
                str(identifier),
                "generate_recurring_drafts",
                None,
                {**payload.model_dump(mode="json"), "count": count},
            )
            return {"count": count}

        return accounting.command(
            key, "generate_recurring:" + str(identifier), payload.model_dump(mode="json"), action
        )

    @router.get("/{identifier}/drafts", response_model=list[DraftOutput])
    def drafts(identifier: UUID, start: date, end: date) -> object:
        schedule(start, end, start, "daily", 0)
        with accounting.engine.connect() as connection:
            plan(connection, str(identifier))
            rows = fetch_all(
                connection,
                (
                    "SELECT d.*,f.status AS event_status,f.effective_date,i.quantity, "
                    "i.gross_fen AS event_gross, i.costs_fen AS event_costs FROM"
                    " investment_drafts d LEFT JOIN financial_events f ON f.id=d.event_id"
                    " LEFT JOIN investment_events i ON i.event_id=d.event_id WHERE "
                    "d.plan_id=:id AND d.scheduled_date BETWEEN :start AND :end ORDER BY "
                    "d.scheduled_date,d.id"
                ),
                {"id": str(identifier), "start": start.isoformat(), "end": end.isoformat()},
            )
            return [
                {
                    **r,
                    "amount_fen": str(
                        r["event_gross"] + r["event_costs"] if r["event_id"] else r["amount_fen"]
                    ),
                    "costs_fen": str(r["event_costs"] if r["event_id"] else r["costs_fen"]),
                }
                for r in rows
            ]

    @router.post("/review", response_model=CountOutput)
    def review(payload: ReviewInput, key: Key) -> object:
        def action(connection: Any) -> dict[str, Any]:
            seen = set()
            for row in payload.rows:
                identifier = str(row.id)
                if identifier in seen:
                    raise RuleError("RECURRING_CONFLICT")
                seen.add(identifier)
                found = fetch_all(
                    connection, "SELECT * FROM investment_drafts WHERE id=:id", {"id": identifier}
                )
                if (
                    not found
                    or found[0]["status"] != "pending"
                    or found[0]["revision"] != row.revision
                ):
                    raise RuleError("RECURRING_CONFLICT")
                old = found[0]
                item = plan(connection, old["plan_id"])
                event_id = None
                if row.decision == "confirm":
                    writable(connection, item)
                    if (
                        row.confirmation_date is None
                        or row.confirmation_date.isoformat() < old["scheduled_date"]
                    ):
                        raise RuleError("RECURRING_CONFIRMATION_REQUIRED")
                    if row.nav_date and row.nav_date > row.confirmation_date:
                        raise RuleError("RECURRING_INVALID_NAV_DATE")
                    try:
                        transaction = TradeInput.model_validate(
                            {
                                "account_id": item["account_id"],
                                "instrument_id": item["instrument_id"],
                                "action": "buy",
                                "effective_date": row.confirmation_date,
                                "quantity": row.quantity,
                                "amount_fen": row.amount_fen,
                                "costs_fen": row.costs_fen,
                                "amount_mode": "net",
                                "note": "定投计划：" + item["name"],
                            }
                        )
                    except ValidationError as error:
                        raise RuleError("RECURRING_INVALID_CONFIRMATION") from error
                    if not 0 <= int(row.costs_fen) < int(row.amount_fen):
                        raise RuleError("RECURRING_INVALID_PLAN")
                    existing = fetch_all(
                        connection,
                        (
                            "SELECT i.quantity,i.gross_fen,i.costs_fen FROM financial_events f "
                            "JOIN investment_events i ON i.event_id=f.id WHERE f.status='active' "
                            "AND f.account_id=:account AND i.instrument_id=:asset AND "
                            "i.action='buy' AND f.effective_date=:day"
                        ),
                        {
                            "account": item["account_id"],
                            "asset": item["instrument_id"],
                            "day": row.confirmation_date.isoformat(),
                        },
                    )
                    from pjz.investment_domain import decimal_value

                    if not payload.allow_possible_duplicate and any(
                        decimal_value(t["quantity"]) == decimal_value(row.quantity)
                        and t["gross_fen"] + t["costs_fen"] == int(row.amount_fen)
                        for t in existing
                    ):
                        raise RuleError("RECURRING_POSSIBLE_DUPLICATE")
                    event_id = investments.save_trade(
                        connection, transaction.model_dump(mode="json")
                    )["id"]
                connection.execute(
                    text(
                        "UPDATE investment_drafts SET status=:status,event_id=:event,nav_date"
                        "=:nav,amount_fen=:amount,costs_fen=:costs,revision=revision+1 WHERE "
                        "id=:id"
                    ),
                    {
                        "id": identifier,
                        "status": "confirmed" if event_id else "skipped",
                        "event": event_id,
                        "nav": row.nav_date.isoformat() if row.nav_date and event_id else None,
                        "amount": int(row.amount_fen) if event_id else old["amount_fen"],
                        "costs": int(row.costs_fen) if event_id else old["costs_fen"],
                    },
                )
                accounting.audit(
                    connection,
                    identifier,
                    "review_recurring_draft",
                    old,
                    row.model_dump(mode="json"),
                )
            return {"count": len(payload.rows)}

        return accounting.command(key, "review_recurring", payload.model_dump(mode="json"), action)

    return router
