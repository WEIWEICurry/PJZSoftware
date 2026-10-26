"""Transactional daily-ledger use cases. Every mutation is replayed and audited."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from pjz.domain import MAX_FEN, RuleError, check_balance, entries_for


def now() -> str:
    return datetime.now(UTC).isoformat()


def fetch_all(
    connection: Connection, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql), params or {}).mappings()]


class Accounting:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def write(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def seed_categories(self) -> None:
        with self.write() as connection:
            ledger_id = connection.execute(text("SELECT id FROM ledger")).scalar_one()
            for direction, names in (
                ("income", ("工资", "奖金", "其他收入")),
                (
                    "expense",
                    (
                        "餐饮",
                        "日用",
                        "交通",
                        "洗澡",
                        "学习",
                        "烟酒",
                        "服饰",
                        "通讯",
                        "零食",
                        "礼物",
                        "娱乐",
                        "快递",
                        "旅行",
                        "水果",
                        "住房",
                        "医疗",
                        "手续费",
                        "其他支出",
                    ),
                ),
            ):
                for name in names:
                    connection.execute(
                        text(
                            "INSERT OR IGNORE INTO categories "
                            "(id,ledger_id,name,direction,created_at,updated_at) "
                            "VALUES (:id,:ledger,:name,:direction,:at,:at)"
                        ),
                        {
                            "id": str(uuid.uuid5(uuid.UUID(ledger_id), direction + name)),
                            "ledger": ledger_id,
                            "name": name,
                            "direction": direction,
                            "at": now(),
                        },
                    )

    def command(
        self,
        key: str,
        operation: str,
        payload: dict[str, Any],
        action: Callable[[Connection], dict[str, Any]],
    ) -> dict[str, Any]:
        digest = hashlib.sha256(
            json.dumps([operation, payload], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        try:
            with self.write() as connection:
                previous = fetch_all(
                    connection, "SELECT * FROM idempotency_records WHERE key=:key", {"key": key}
                )
                if previous:
                    if previous[0]["payload_hash"] != digest:
                        raise RuleError("IDEMPOTENCY_CONFLICT")
                    return dict(json.loads(previous[0]["result_json"]))
                result = action(connection)
                self.rebuild(connection)
                connection.execute(text("UPDATE ledger SET revision=revision+1"))
                connection.execute(
                    text("INSERT INTO idempotency_records VALUES (:key,:hash,:result,:at)"),
                    {"key": key, "hash": digest, "result": json.dumps(result), "at": now()},
                )
                return result
        except IntegrityError as error:
            raise RuleError("DUPLICATE_OR_INVALID_REFERENCE") from error

    def audit(
        self,
        connection: Connection,
        entity_id: str,
        operation: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO operation_revisions VALUES (:id,(SELECT id FROM ledger),"
                ":entity,:operation,:before,:after,:at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "entity": entity_id,
                "operation": operation,
                "before": json.dumps(before) if before else None,
                "after": json.dumps(after),
                "at": now(),
            },
        )

    @staticmethod
    def account_rows(connection: Connection) -> list[dict[str, Any]]:
        rows = fetch_all(
            connection,
            "SELECT a.*, COALESCE(SUM(c.delta_fen),0) AS balance_fen FROM accounts a "
            "LEFT JOIN cash_entries c ON c.account_id=a.id "
            "GROUP BY a.id ORDER BY a.created_at,a.id",
        )
        for row in rows:
            row["balance_fen"] = str(row["balance_fen"])
            row["archived"] = bool(row["archived"])
        return rows

    def accounts(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return self.account_rows(connection)

    def categories(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return fetch_all(
                connection, "SELECT * FROM categories WHERE archived=0 ORDER BY direction,name"
            )

    def create_category(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            identifier = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO categories (id,ledger_id,name,direction,created_at,updated_at) "
                    "VALUES (:id,(SELECT id FROM ledger),:name,:direction,:at,:at)"
                ),
                {"id": identifier, **payload, "at": now()},
            )
            result = fetch_all(
                connection, "SELECT * FROM categories WHERE id=:id", {"id": identifier}
            )[0]
            self.audit(connection, identifier, "create_category", None, result)
            return result

        return self.command(key, "create_category", payload, action)

    def create_account(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            identifier = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO accounts "
                    "(id,ledger_id,name,kind,opening_date,created_at,updated_at) "
                    "VALUES (:id,(SELECT id FROM ledger),:name,:kind,:date,:at,:at)"
                ),
                {
                    "id": identifier,
                    "name": payload["name"],
                    "kind": payload["kind"],
                    "date": payload["opening_date"],
                    "at": now(),
                },
            )
            self.insert_event(
                connection,
                {
                    "kind": "opening",
                    "account_id": identifier,
                    "effective_date": payload["opening_date"],
                    "amount_fen": payload["opening_fen"],
                    "fee_fen": "0",
                    "note": "期初余额",
                    "category_id": None,
                    "target_account_id": None,
                    "original_event_id": None,
                },
            )
            result = {"id": identifier}
            self.audit(connection, identifier, "create_account", None, payload)
            return result

        return self.command(key, "create_account", payload, action)

    def update_account(self, identifier: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            rows = fetch_all(connection, "SELECT * FROM accounts WHERE id=:id", {"id": identifier})
            if not rows:
                raise RuleError("ACCOUNT_NOT_FOUND")
            before = rows[0]
            if payload["revision"] != before["revision"]:
                raise RuleError("REVISION_CONFLICT")
            if payload["archived"]:
                balance = connection.execute(
                    text(
                        "SELECT COALESCE(SUM(delta_fen),0) FROM cash_entries WHERE account_id=:id"
                    ),
                    {"id": identifier},
                ).scalar_one()
                if balance:
                    raise RuleError("ACCOUNT_NOT_EMPTY")
            connection.execute(
                text(
                    "UPDATE accounts SET name=:name, archived=:archived, revision=revision+1,"
                    "updated_at=:at WHERE id=:id"
                ),
                {
                    "id": identifier,
                    "name": payload["name"],
                    "archived": int(payload["archived"]),
                    "at": now(),
                },
            )
            self.audit(connection, identifier, "update_account", before, payload)
            return {"id": identifier}

        return self.command(key, "update_account:" + identifier, payload, action)

    def insert_event(self, connection: Connection, payload: dict[str, Any]) -> dict[str, Any]:
        identifier = str(uuid.uuid4())
        sequence = connection.execute(
            text("SELECT COALESCE(MAX(sequence),0)+1 FROM financial_events")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO financial_events "
                "(id,ledger_id,kind,effective_date,sequence,account_id,target_account_id,"
                "category_id,original_event_id,amount_fen,fee_fen,note,created_at,updated_at) "
                "VALUES (:id,(SELECT id FROM ledger),:kind,:effective_date,:sequence,:account_id,"
                ":target_account_id,:category_id,:original_event_id,:amount_fen,:fee_fen,:note,:at,:at)"
            ),
            {
                **payload,
                "id": identifier,
                "sequence": sequence,
                "amount_fen": int(payload["amount_fen"]),
                "fee_fen": int(payload["fee_fen"]),
                "at": now(),
            },
        )
        return fetch_all(
            connection, "SELECT * FROM financial_events WHERE id=:id", {"id": identifier}
        )[0]

    def ensure_writable_accounts(self, connection: Connection, payload: dict[str, Any]) -> None:
        for identifier in (payload["account_id"], payload.get("target_account_id")):
            if not identifier:
                continue
            rows = fetch_all(connection, "SELECT * FROM accounts WHERE id=:id", {"id": identifier})
            if not rows:
                raise RuleError("ACCOUNT_NOT_FOUND")
            if rows[0]["archived"]:
                raise RuleError("ACCOUNT_ARCHIVED")

    def create_event(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            self.ensure_writable_accounts(connection, payload)
            event = self.insert_event(connection, payload)
            self.audit(connection, event["id"], "create_event", None, event)
            return self.serialize_event(event)

        return self.command(key, "create_event", payload, action)

    def change_event(
        self, identifier: str, payload: dict[str, Any], key: str, void: bool = False
    ) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            rows = fetch_all(
                connection, "SELECT * FROM financial_events WHERE id=:id", {"id": identifier}
            )
            if not rows:
                raise RuleError("EVENT_NOT_FOUND")
            before = rows[0]
            if before["revision"] != payload["revision"] or before["status"] == "void":
                raise RuleError("REVISION_CONFLICT")
            if before["kind"] == "opening":
                raise RuleError("OPENING_IMMUTABLE")
            self.ensure_writable_accounts(connection, before)
            if void:
                connection.execute(
                    text(
                        "UPDATE financial_events SET status='void',revision=revision+1,"
                        "updated_at=:at WHERE id=:id"
                    ),
                    {"at": now(), "id": identifier},
                )
            else:
                self.ensure_writable_accounts(connection, payload)
                connection.execute(
                    text(
                        "UPDATE financial_events SET kind=:kind,effective_date=:effective_date,"
                        "account_id=:account_id,target_account_id=:target_account_id,"
                        "category_id=:category_id,original_event_id=:original_event_id,"
                        "amount_fen=:amount_fen,fee_fen=:fee_fen,note=:note,"
                        "revision=revision+1,updated_at=:at WHERE id=:id"
                    ),
                    {
                        **payload,
                        "amount_fen": int(payload["amount_fen"]),
                        "fee_fen": int(payload["fee_fen"]),
                        "id": identifier,
                        "at": now(),
                    },
                )
            after = fetch_all(
                connection, "SELECT * FROM financial_events WHERE id=:id", {"id": identifier}
            )[0]
            self.audit(
                connection, identifier, "void_event" if void else "update_event", before, after
            )
            return self.serialize_event(after)

        return self.command(key, ("void:" if void else "update:") + identifier, payload, action)

    @staticmethod
    def serialize_event(event: dict[str, Any]) -> dict[str, Any]:
        return {**event, "amount_fen": str(event["amount_fen"]), "fee_fen": str(event["fee_fen"])}

    def rebuild(self, connection: Connection, persist: bool = True) -> None:
        accounts = {row["id"]: row for row in fetch_all(connection, "SELECT * FROM accounts")}
        categories = {row["id"]: row for row in fetch_all(connection, "SELECT * FROM categories")}
        events = fetch_all(
            connection,
            "SELECT * FROM financial_events WHERE status='active' "
            "ORDER BY effective_date,sequence,id",
        )
        event_map = {row["id"]: row for row in events}
        balances = {identifier: 0 for identifier in accounts}
        refunded: dict[str, int] = {}
        expected_entries: dict[tuple[str, str], int] = {}
        if persist:
            connection.execute(text("DELETE FROM cash_entries"))
        for item in events:
            account = accounts[item["account_id"]]
            day = date.fromisoformat(item["effective_date"])
            if day > date.today():
                raise RuleError("FUTURE_DATE")
            related = [account]
            target = accounts.get(item["target_account_id"])
            if target:
                related.append(target)
            if any(item["effective_date"] < row["opening_date"] for row in related):
                raise RuleError("BEFORE_OPENING")
            amount = item["amount_fen"]
            fee = item["fee_fen"]
            kind = item["kind"]
            if type(amount) is not int or type(fee) is not int or fee < 0:
                raise RuleError("INVALID_AMOUNT")
            if abs(amount) > MAX_FEN or fee > MAX_FEN:
                raise RuleError("AMOUNT_OUT_OF_RANGE")
            if kind not in ("opening", "adjustment") and amount <= 0:
                raise RuleError("INVALID_AMOUNT")
            if kind == "opening" and amount < 0:
                raise RuleError("INVALID_AMOUNT")
            if kind == "adjustment" and (not amount or not item["note"].strip()):
                raise RuleError("ADJUSTMENT_REASON_REQUIRED")
            if kind != "transfer" and (fee or target):
                raise RuleError("INVALID_EVENT_FIELDS")
            if kind == "transfer" and not target:
                raise RuleError("TARGET_REQUIRED")
            if kind != "refund" and item["original_event_id"]:
                raise RuleError("INVALID_EVENT_FIELDS")
            category = categories.get(item["category_id"])
            if kind in ("income", "expense", "refund") or fee:
                expected = "income" if kind == "income" else "expense"
                if not category or category["direction"] != expected:
                    raise RuleError("CATEGORY_MISMATCH")
            elif item["category_id"]:
                raise RuleError("INVALID_EVENT_FIELDS")
            if kind == "refund":
                original = event_map.get(item["original_event_id"])
                if not original or original["kind"] != "expense":
                    raise RuleError("REFUND_SOURCE_INVALID")
                if (original["effective_date"], original["sequence"]) > (
                    item["effective_date"],
                    item["sequence"],
                ):
                    raise RuleError("REFUND_BEFORE_EXPENSE")
                if original["category_id"] != item["category_id"]:
                    raise RuleError("CATEGORY_MISMATCH")
                refunded[original["id"]] = refunded.get(original["id"], 0) + amount
                if refunded[original["id"]] > original["amount_fen"]:
                    raise RuleError("REFUND_EXCEEDS_EXPENSE")
            for entry in entries_for(
                kind,
                account["id"],
                account["kind"],
                amount,
                target["id"] if target else None,
                target["kind"] if target else None,
                fee,
            ):
                balances[entry.account_id] += entry.delta_fen
                check_balance(balances[entry.account_id])
                expected_entries[(item["id"], entry.account_id)] = entry.delta_fen
                if persist:
                    connection.execute(
                        text("INSERT INTO cash_entries VALUES (:event,:account,:delta)"),
                        {
                            "event": item["id"],
                            "account": entry.account_id,
                            "delta": entry.delta_fen,
                        },
                    )
        if not persist:
            actual = {
                (row["event_id"], row["account_id"]): row["delta_fen"]
                for row in fetch_all(connection, "SELECT * FROM cash_entries")
            }
            if actual != expected_entries:
                raise RuleError("PROJECTION_MISMATCH")

    def events(
        self,
        start: str,
        end: str,
        account_id: str | None = None,
        kind: str | None = None,
        category_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = "effective_date>=:start AND effective_date<=:end"
        params: dict[str, Any] = {"start": start, "end": end, "limit": limit, "offset": offset}
        if account_id:
            where += " AND (account_id=:account OR target_account_id=:account)"
            params["account"] = account_id
        if kind:
            where += " AND kind=:kind"
            params["kind"] = kind
        if category_id:
            where += " AND category_id=:category"
            params["category"] = category_id
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            total = connection.execute(
                text("SELECT COUNT(*) FROM financial_events WHERE " + where), params
            ).scalar_one()
            rows = fetch_all(
                connection,
                "SELECT * FROM financial_events WHERE "
                + where
                + " ORDER BY effective_date DESC,sequence DESC LIMIT :limit OFFSET :offset",
                params,
            )
        return {"items": [self.serialize_event(row) for row in rows], "total": total}

    def summary(self, start: str, end: str) -> dict[str, str]:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            accounts = self.account_rows(connection)
            rows = fetch_all(
                connection,
                "SELECT kind,amount_fen,fee_fen FROM financial_events "
                "WHERE status='active' AND effective_date>=:start AND effective_date<=:end",
                {"start": start, "end": end},
            )
        income = sum(row["amount_fen"] for row in rows if row["kind"] == "income")
        expense = sum(row["amount_fen"] for row in rows if row["kind"] == "expense")
        expense -= sum(row["amount_fen"] for row in rows if row["kind"] == "refund")
        expense += sum(row["fee_fen"] for row in rows if row["kind"] == "transfer")
        assets = sum(int(row["balance_fen"]) for row in accounts if row["kind"] != "liability")
        debt = sum(int(row["balance_fen"]) for row in accounts if row["kind"] == "liability")
        return {
            key: str(value)
            for key, value in {
                "income_fen": income,
                "expense_fen": expense,
                "surplus_fen": income - expense,
                "assets_fen": assets,
                "debt_fen": debt,
                "net_fen": assets - debt,
            }.items()
        }
