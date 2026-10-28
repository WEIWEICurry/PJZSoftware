"""Transactional investment facts and disposable position projections."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from pjz.accounting import Accounting, fetch_all, now
from pjz.domain import RuleError
from pjz.investment_domain import Position, decimal_text, decimal_value, holding_share_bps


class Investments:
    def __init__(self, accounting: Accounting) -> None:
        self.accounting = accounting

    @staticmethod
    def replay(connection: Connection) -> tuple[dict[tuple[str, str], Position], dict[str, int]]:
        if connection.exec_driver_sql("PRAGMA user_version").scalar_one() < 6:
            return {}, {}
        instruments = {r["id"]: r for r in fetch_all(connection, "SELECT * FROM instruments")}
        for item in instruments.values():
            if not re.fullmatch(r"[0-9]{6}", item["code"]) or not item["name"].strip():
                raise RuleError("INVESTMENT_INVALID_INSTRUMENT")
            if (item["market"] == "FUND") != (item["kind"] == "fund"):
                raise RuleError("INVESTMENT_INVALID_INSTRUMENT")
        for item in fetch_all(connection, "SELECT * FROM valuations"):
            decimal_value(item["price"])
            if date.fromisoformat(item["price_date"]) > date.today():
                raise RuleError("FUTURE_DATE")
        rows = fetch_all(
            connection,
            "SELECT f.*,i.instrument_id,i.action,i.quantity,i.gross_fen,i.costs_fen,"
            "i.cost_basis_fen,a.kind AS account_kind FROM financial_events f "
            "JOIN investment_events i ON i.event_id=f.id JOIN accounts a ON a.id=f.account_id "
            "ORDER BY f.effective_date,f.sequence,f.id",
        )
        expected = {
            r["id"]
            for r in fetch_all(
                connection, "SELECT id FROM financial_events WHERE kind='investment'"
            )
        }
        if expected != {r["id"] for r in rows}:
            raise RuleError("INVESTMENT_INVALID_FACTS")
        positions: dict[tuple[str, str], Position] = {}
        cash: dict[str, int] = {}
        for row in rows:
            if row["kind"] != "investment" or row["account_kind"] in ("liability", "receivable"):
                raise RuleError("INVESTMENT_INVALID_FACTS")
            if any(
                row[k]
                for k in (
                    "amount_fen",
                    "fee_fen",
                    "target_account_id",
                    "category_id",
                    "original_event_id",
                )
            ):
                raise RuleError("INVESTMENT_INVALID_FACTS")
            units = decimal_value(row["quantity"])
            if (
                instruments[row["instrument_id"]]["kind"] != "fund"
                and units != units.to_integral_value()
            ):
                raise RuleError("INVESTMENT_WHOLE_SHARES_REQUIRED")
            if row["status"] != "active":
                continue
            key = (row["account_id"], row["instrument_id"])
            position = positions.setdefault(key, Position())
            try:
                cash[row["id"]] = position.apply(
                    row["action"],
                    row["quantity"],
                    row["gross_fen"],
                    row["costs_fen"],
                    row["cost_basis_fen"],
                )
            except RuleError as error:
                raise RuleError(
                    str(error), row["id"], row["effective_date"], row["sequence"]
                ) from error
        # A price or later quantity change must not commit an unrenderable valuation.
        latest_prices: dict[str, str] = {}
        for valuation in fetch_all(
            connection, "SELECT * FROM valuations WHERE status='active' ORDER BY price_date DESC"
        ):
            latest_prices.setdefault(valuation["instrument_id"], valuation["price"])
        for (_, instrument_id), position in positions.items():
            if instrument_id in latest_prices:
                position.market_value(latest_prices[instrument_id])
        return positions, cash

    def instrument(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            if (payload["market"] == "FUND") != (payload["kind"] == "fund"):
                raise RuleError("INVESTMENT_INVALID_INSTRUMENT")
            identifier = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO instruments "
                    "(id,ledger_id,market,code,name,kind,created_at,updated_at) "
                    "VALUES (:id,(SELECT id FROM ledger),:market,:code,:name,:kind,:at,:at)"
                ),
                {**payload, "id": identifier, "at": now()},
            )
            self.accounting.audit(connection, identifier, "create_instrument", None, payload)
            return {"id": identifier}

        return self.accounting.command(key, "instrument", payload, action)

    def trade(
        self, payload: dict[str, Any], key: str, identifier: str | None = None
    ) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            self.accounting.ensure_writable_accounts(connection, payload)
            before = None
            if identifier:
                rows = fetch_all(
                    connection,
                    "SELECT f.*,i.* FROM financial_events f JOIN "
                    "investment_events i ON i.event_id=f.id WHERE f.id=:id",
                    {"id": identifier},
                )
                if (
                    not rows
                    or rows[0]["revision"] != payload["revision"]
                    or rows[0]["status"] != "active"
                ):
                    raise RuleError("REVISION_CONFLICT")
                before = rows[0]
                self.accounting.ensure_writable_accounts(connection, before)
                # Identity stays stable; correction changes amounts, date or note.
                if any(payload[k] != before[k] for k in ("account_id", "instrument_id", "action")):
                    raise RuleError("INVESTMENT_IDENTITY_IMMUTABLE")
                event_id = identifier
                connection.execute(
                    text(
                        "UPDATE financial_events SET "
                        "effective_date=:effective_date,note=:note,"
                        "revision=revision+1,updated_at=:at WHERE id=:id"
                    ),
                    {**payload, "at": now(), "id": identifier},
                )
                connection.execute(
                    text("DELETE FROM investment_events WHERE event_id=:id"), {"id": identifier}
                )
            else:
                event_id = self.accounting.insert_event(
                    connection,
                    {
                        "kind": "investment",
                        "account_id": payload["account_id"],
                        "effective_date": payload["effective_date"],
                        "amount_fen": "0",
                        "fee_fen": "0",
                        "target_account_id": None,
                        "category_id": None,
                        "original_event_id": None,
                        "note": payload["note"],
                    },
                )["id"]
            gross = int(payload["amount_fen"])
            fee = int(payload["costs_fen"])
            if payload["amount_mode"] == "net":
                gross += -fee if payload["action"] == "buy" else fee
            basis = payload["cost_basis_fen"]
            connection.execute(
                text(
                    "INSERT INTO investment_events VALUES "
                    "(:id,:instrument_id,:action,:quantity,:gross,:fee,:basis)"
                ),
                {
                    **payload,
                    "id": event_id,
                    "gross": gross,
                    "fee": fee,
                    "basis": None if basis is None else int(basis),
                },
            )
            self.accounting.audit(
                connection,
                event_id,
                "update_investment" if identifier else "create_investment",
                before,
                payload,
            )
            return {"id": event_id}

        return self.accounting.command(key, "trade:" + (identifier or "new"), payload, action)

    def void_trade(self, identifier: str, revision: int, key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            rows = fetch_all(
                connection,
                "SELECT * FROM financial_events WHERE id=:id AND kind='investment'",
                {"id": identifier},
            )
            if not rows or rows[0]["status"] != "active" or rows[0]["revision"] != revision:
                raise RuleError("REVISION_CONFLICT")
            self.accounting.ensure_writable_accounts(connection, rows[0])
            connection.execute(
                text(
                    "UPDATE financial_events SET "
                    "status='void',revision=revision+1,updated_at=:at WHERE id=:id"
                ),
                {"at": now(), "id": identifier},
            )
            self.accounting.audit(
                connection, identifier, "void_investment", rows[0], {"status": "void"}
            )
            return {"id": identifier}

        return self.accounting.command(
            key, "void_investment:" + identifier, {"revision": revision}, action
        )

    def price(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            decimal_value(payload["price"])
            rows = fetch_all(
                connection,
                "SELECT * FROM valuations WHERE instrument_id=:instrument_id AND "
                "price_date=:price_date",
                payload,
            )
            before = rows[0] if rows else None
            if payload["revision"] != (before["revision"] if before else 0):
                raise RuleError("REVISION_CONFLICT")
            identifier = before["id"] if before else str(uuid.uuid4())
            if before:
                connection.execute(
                    text(
                        "UPDATE valuations SET "
                        "price=:price,status=:status,revision=revision+1,"
                        "updated_at=:at WHERE id=:id"
                    ),
                    {**payload, "id": identifier, "at": now()},
                )
            else:
                if payload["status"] != "active":
                    raise RuleError("REVISION_CONFLICT")
                connection.execute(
                    text(
                        "INSERT INTO valuations "
                        "(id,ledger_id,instrument_id,price_date,price,status,"
                        "created_at,updated_at) VALUES (:id,(SELECT id FROM "
                        "ledger),:instrument_id,:price_date,:price,:status,:at,:at)"
                    ),
                    {**payload, "id": identifier, "at": now()},
                )
            self.accounting.audit(connection, identifier, "save_valuation", before, payload)
            return {"id": identifier}

        return self.accounting.command(key, "valuation", payload, action)

    def page(self) -> dict[str, Any]:
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            positions, _ = self.replay(connection)
            instruments = fetch_all(
                connection, "SELECT * FROM instruments ORDER BY kind,market,code"
            )
            prices = fetch_all(connection, "SELECT * FROM valuations ORDER BY price_date DESC,id")
            latest: dict[str, dict[str, Any]] = {}
            for valuation in prices:
                if valuation["status"] == "active":
                    latest.setdefault(valuation["instrument_id"], valuation)
            items = []
            total = 0
            missing = 0
            unknown_cost = 0
            realized = 0
            unrealized = 0
            for (account_id, instrument_id), position in positions.items():
                price = latest.get(instrument_id)
                value = (
                    position.market_value(price["price"])
                    if price
                    else (0 if not position.quantity else None)
                )
                profit = (
                    value - position.cost
                    if value is not None and position.cost is not None
                    else None
                )
                total += value or 0
                missing += int(value is None)
                unknown_cost += int(position.cost is None)
                realized += position.realized
                unrealized += profit or 0
                items.append(
                    {
                        "account_id": account_id,
                        "instrument_id": instrument_id,
                        "quantity": decimal_text(position.quantity),
                        "cost_fen": None if position.cost is None else str(position.cost),
                        "realized_fen": str(position.realized),
                        "value_fen": None if value is None else str(value),
                        "unrealized_fen": None if profit is None else str(profit),
                        "price": price["price"] if price else None,
                        "price_date": price["price_date"] if price else None,
                    }
                )
            for item in items:
                item["share_bps"] = holding_share_bps(
                    None if item["value_fen"] is None else int(item["value_fen"]),
                    total,
                    missing == 0,
                )
            accounts = self.accounting.account_rows(connection)
            net = sum(
                int(r["balance_fen"]) * (-1 if r["kind"] == "liability" else 1) for r in accounts
            )
            trades = fetch_all(
                connection,
                "SELECT "
                "f.id,f.account_id,f.effective_date,f.note,f.status,f.revision,"
                "f.sequence,i.* FROM financial_events f JOIN investment_events i "
                "ON i.event_id=f.id ORDER BY f.effective_date DESC,f.sequence DESC",
            )
            for trade in trades:
                for field in ("gross_fen", "costs_fen", "cost_basis_fen"):
                    if trade[field] is not None:
                        trade[field] = str(trade[field])
            return {
                "instruments": instruments,
                "positions": items,
                "trades": trades,
                "valuations": prices,
                "known_value_fen": str(total),
                "missing_price_count": missing,
                "unknown_cost_count": unknown_cost,
                "realized_fen": str(realized),
                "unrealized_fen": None if missing or unknown_cost else str(unrealized),
                "total_profit_fen": None if missing or unknown_cost else str(realized + unrealized),
                "known_net_fen": str(net + total),
                "net_fen": None if missing else str(net + total),
            }
