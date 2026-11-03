"""Previewed ownership correction with unchanged cash and verified safety backup."""

import secrets
import threading
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import Connection, text

from pjz.accounting import Accounting, fetch_all, now
from pjz.daily_api import Key, StrictInput
from pjz.domain import RuleError
from pjz.investments import Investments
from pjz.storage import LedgerStore, write_verified_backup


class TransferInput(StrictInput):
    instrument_id: UUID
    source_account_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_account_id: UUID


class TransferCommit(TransferInput):
    ledger_revision: int = Field(ge=1)
    preview_token: str = Field(min_length=20, max_length=128)


def holding_transfer_router(store: LedgerStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/investments/holding-transfer")
    accounting = Accounting(store.engine)
    previews: dict[str, tuple[dict[str, Any], int, float]] = {}
    lock = threading.Lock()

    def apply(connection: Connection, data: dict[str, Any]) -> int:
        target = data["target_account_id"]
        sources = set(data["source_account_ids"])
        if target in sources:
            raise RuleError("HOLDING_TRANSFER_TARGET_SOURCE")
        accounting.ensure_writable_accounts(connection, {"account_id": target})
        accounts = {a["id"]: a for a in fetch_all(connection, "SELECT * FROM accounts")}
        if accounts[target]["kind"] in ("receivable", "liability"):
            raise RuleError("CASH_ACCOUNT_REQUIRED")
        if not sources.issubset(accounts):
            raise RuleError("ACCOUNT_NOT_FOUND")
        cash_before = {
            r["account_id"]: r["amount"]
            for r in fetch_all(
                connection,
                "SELECT account_id,SUM(delta_fen) AS amount FROM cash_entries GROUP BY account_id",
            )
        }
        count = 0
        for source in sorted(sources):
            accounting.ensure_writable_accounts(connection, {"account_id": source})
            rows = fetch_all(
                connection,
                "SELECT f.id,i.action,i.cash_account_id FROM financial_events f JOIN "
                "investment_events i ON i.event_id=f.id WHERE f.account_id=:source AND "
                "i.instrument_id=:asset",
                {"source": source, "asset": data["instrument_id"]},
            )
            for row in rows:
                cash = (
                    row["cash_account_id"] or source
                    if row["action"] in ("buy", "sell", "cash_dividend", "reinvest")
                    else None
                )
                connection.execute(
                    text("UPDATE investment_events SET cash_account_id=:cash WHERE event_id=:id"),
                    {"cash": cash, "id": row["id"]},
                )
                connection.execute(
                    text(
                        "UPDATE financial_events SET account_id=:target,revision=revision+1 WHERE "
                        "id=:id"
                    ),
                    {"target": target, "id": row["id"], "at": now()},
                )
                accounting.audit(
                    connection,
                    row["id"],
                    "transfer_holding_event",
                    {"account_id": source, "cash_account_id": row["cash_account_id"]},
                    {"account_id": target, "cash_account_id": cash},
                )
                count += 1
            connection.execute(
                text(
                    "UPDATE investment_plans SET "
                    "cash_account_id=COALESCE(cash_account_id,account_id),"
                    "account_id=:target,revision=revision+1 "
                    "WHERE account_id=:source AND instrument_id=:asset"
                ),
                {"target": target, "source": source, "asset": data["instrument_id"]},
            )
        if not count:
            raise RuleError("HOLDING_TRANSFER_EMPTY")
        accounting.rebuild(connection)
        cash_after = {
            r["account_id"]: r["amount"]
            for r in fetch_all(
                connection,
                "SELECT account_id,SUM(delta_fen) AS amount FROM cash_entries GROUP BY account_id",
            )
        }
        if cash_before != cash_after:
            raise RuleError("HOLDING_TRANSFER_CASH_CHANGED")
        return count

    def simulate(connection: Connection, data: dict[str, Any]) -> dict[str, Any]:
        before, _, _ = Investments.replay_details(connection)
        previous_realized = sum(
            p.realized
            for (account, asset), p in before.items()
            if asset == data["instrument_id"]
            and account in {*data["source_account_ids"], data["target_account_id"]}
        )
        connection.exec_driver_sql("SAVEPOINT holding_preview")
        try:
            count = apply(connection, data)
            positions, _, _ = Investments.replay_details(connection)
            p = positions.get((data["target_account_id"], data["instrument_id"]))
            return {
                "event_count": count,
                "quantity": str(p.quantity) if p else "0",
                "cost_fen": str(p.cost) if p and p.cost is not None else None,
                "realized_fen": str(p.realized) if p else "0",
                "previous_realized_fen": str(previous_realized),
            }
        finally:
            connection.exec_driver_sql("ROLLBACK TO SAVEPOINT holding_preview")
            connection.exec_driver_sql("RELEASE SAVEPOINT holding_preview")

    @router.post("/preview")
    def preview(payload: TransferInput) -> dict[str, Any]:
        with accounting.write() as connection:
            result = simulate(connection, payload.model_dump(mode="json"))
            result["ledger_revision"] = connection.execute(
                text("SELECT revision FROM ledger")
            ).scalar_one()
            token = secrets.token_urlsafe(32)
            with lock:
                for old_token, value in list(previews.items()):
                    if value[2] < time.monotonic():
                        previews.pop(old_token, None)
                if len(previews) >= 20:
                    previews.pop(next(iter(previews)))
                previews[token] = (
                    payload.model_dump(mode="json"),
                    result["ledger_revision"],
                    time.monotonic() + 300,
                )
            return {**result, "preview_token": token}

    @router.post("/commit")
    def commit(payload: TransferCommit, key: Key) -> dict[str, Any]:
        data = payload.model_dump(mode="json")

        def action(connection: Connection) -> dict[str, Any]:
            with lock:
                item = previews.get(payload.preview_token)
            if not item or item[2] < time.monotonic():
                raise RuleError("PREVIEW_EXPIRED")
            if (
                item[0]
                != {
                    k: data[k] for k in ("instrument_id", "source_account_ids", "target_account_id")
                }
                or item[1] != payload.ledger_revision
            ):
                raise RuleError("REVISION_CONFLICT")
            if (
                connection.execute(text("SELECT revision FROM ledger")).scalar_one()
                != payload.ledger_revision
            ):
                raise RuleError("REVISION_CONFLICT")
            result = simulate(connection, data)
            path = (
                store.directory
                / "backups"
                / ("before-holding-transfer-" + uuid4().hex + ".pjzbackup")
            )
            try:
                path.parent.mkdir(exist_ok=True)
                write_verified_backup(path, store.backup())
            except Exception as error:
                raise RuleError("BACKUP_FAILED") from error
            apply(connection, data)
            accounting.audit(
                connection, data["target_account_id"], "transfer_holding_ownership", None, data
            )
            return {**result, "backup_path": str(path)}

        result = accounting.command(key, "transfer_holding_ownership", data, action)
        with lock:
            previews.pop(payload.preview_token, None)
        return result

    return router
