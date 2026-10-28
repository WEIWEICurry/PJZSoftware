"""Previewed physical account deletion; backups and graph validation are mandatory."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text

from pjz.accounting import Accounting, fetch_all
from pjz.domain import RuleError
from pjz.storage import DataError, LedgerStore, inspect_backup


class AccountDeletion:
    def __init__(self, store: LedgerStore) -> None:
        self.store = store
        self.accounting = Accounting(store.engine)
        self.previews: dict[str, tuple[str, int, float]] = {}
        self.lock = threading.Lock()

    def plan(self, connection: Connection, identifier: str) -> dict[str, Any]:
        accounts = {item["id"]: item for item in self.accounting.account_rows(connection)}
        account = accounts.get(identifier)
        if account is None:
            raise RuleError("ACCOUNT_NOT_FOUND")
        if not account["archived"]:
            raise RuleError("ACCOUNT_NOT_ARCHIVED")
        if int(account["balance_fen"]) != 0:
            raise RuleError("ACCOUNT_NOT_EMPTY")
        if connection.exec_driver_sql("PRAGMA user_version").scalar_one() >= 6:
            if fetch_all(
                connection,
                "SELECT id FROM financial_events WHERE account_id=:id AND "
                "kind='investment' LIMIT 1",
                {"id": identifier},
            ):
                raise RuleError("INVESTMENT_ACCOUNT_HAS_HISTORY")
        events = fetch_all(connection, "SELECT * FROM financial_events")
        removed = {
            item["id"]
            for item in events
            if identifier in (item["account_id"], item["target_account_id"])
        }
        children: dict[str, list[str]] = {}
        for item in events:
            if item["original_event_id"]:
                children.setdefault(item["original_event_id"], []).append(item["id"])
        pending = list(removed)
        while pending:
            for child in children.get(pending.pop(), []):
                if child not in removed:
                    removed.add(child)
                    pending.append(child)
        related = [item for item in events if item["id"] in removed]
        affected = {
            account_id
            for item in related
            for account_id in (item["account_id"], item["target_account_id"])
            if account_id and account_id != identifier
        }
        deleted_deltas: dict[str, int] = {}
        for entry in fetch_all(connection, "SELECT * FROM cash_entries"):
            if entry["event_id"] in removed:
                key = entry["account_id"]
                deleted_deltas[key] = deleted_deltas.get(key, 0) + entry["delta_fen"]
        impacts = [
            {
                "account_id": account_id,
                "name": accounts[account_id]["name"],
                "before_fen": accounts[account_id]["balance_fen"],
                "after_fen": str(
                    int(accounts[account_id]["balance_fen"]) - deleted_deltas.get(account_id, 0)
                ),
            }
            for account_id in sorted(affected, key=lambda value: accounts[value]["name"])
        ]
        return {
            "account_id": identifier,
            "account_name": account["name"],
            "event_count": len(removed),
            "refund_count": sum(item["kind"] == "refund" for item in related),
            "transfer_count": sum(item["kind"] == "transfer" for item in related),
            "other_accounts": impacts,
            "_event_ids": removed,
        }

    @staticmethod
    def bulk(connection: Connection, sql: str, identifiers: set[str]) -> None:
        if identifiers:
            connection.execute(
                text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": sorted(identifiers)}
            )

    def remove(self, connection: Connection, plan: dict[str, Any]) -> None:
        connection.exec_driver_sql("PRAGMA secure_delete=ON")
        event_ids: set[str] = plan["_event_ids"]
        identifiers = event_ids | {plan["account_id"]}
        self.bulk(connection, "DELETE FROM cash_entries WHERE event_id IN :ids", event_ids)
        # Clear intra-deletion refund references before removing both sides of the graph.
        self.bulk(
            connection,
            "UPDATE financial_events SET original_event_id=NULL WHERE id IN :ids",
            event_ids,
        )
        self.bulk(connection, "DELETE FROM financial_events WHERE id IN :ids", event_ids)
        connection.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": plan["account_id"]})
        revisions = fetch_all(connection, "SELECT * FROM operation_revisions")
        removed_revisions = {
            row["id"]
            for row in revisions
            if row["entity_id"] in identifiers
            or any(
                identifier in (row["before_json"] or "") + row["after_json"]
                for identifier in identifiers
            )
        }
        self.bulk(connection, "DELETE FROM operation_revisions WHERE id IN :ids", removed_revisions)
        for row in fetch_all(connection, "SELECT key,result_json FROM idempotency_records"):
            if any(identifier in row["result_json"] for identifier in identifiers):
                # Retain only a retry tombstone, never the deleted transaction payload.
                connection.execute(
                    text("UPDATE idempotency_records SET result_json=:purged WHERE key=:key"),
                    {"key": row["key"], "purged": json.dumps({"_purged": True})},
                )

    def simulate(self, connection: Connection, plan: dict[str, Any]) -> str | None:
        connection.exec_driver_sql("SAVEPOINT delete_account_preview")
        try:
            self.remove(connection, plan)
            self.accounting.rebuild(connection)
            return None
        except RuleError as error:
            return str(error)
        finally:
            connection.exec_driver_sql("ROLLBACK TO SAVEPOINT delete_account_preview")
            connection.exec_driver_sql("RELEASE SAVEPOINT delete_account_preview")

    def preview(self, identifier: str) -> dict[str, Any]:
        with self.accounting.write() as connection:
            plan = self.plan(connection, identifier)
            reason = self.simulate(connection, plan)
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.previews = {
                key: value for key, value in self.previews.items() if value[2] > time.monotonic()
            }
            if len(self.previews) >= 20:
                self.previews.pop(next(iter(self.previews)))
            self.previews[token] = (identifier, revision, time.monotonic() + 120)
        return {key: value for key, value in plan.items() if not key.startswith("_")} | {
            "preview_token": token,
            "can_delete": reason is None,
            "reason": reason,
        }

    def backup(self) -> Path:
        directory = self.store.directory / "backups"
        destination = directory / ("before-delete-" + uuid.uuid4().hex + ".pjzbackup")
        temporary = destination.with_suffix(".tmp")
        try:
            directory.mkdir(exist_ok=True)
            temporary.write_bytes(self.store.backup())
            inspect_backup(temporary.read_bytes())
            temporary.replace(destination)
            return destination
        except (OSError, DataError, sqlite3.Error) as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # An incomplete .tmp is never treated as a valid backup.
            raise RuleError("BACKUP_FAILED") from error

    def commit(self, identifier: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            with self.lock:
                preview = self.previews.get(payload["preview_token"])
            if preview is None or preview[2] < time.monotonic():
                raise RuleError("PREVIEW_EXPIRED")
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
            if preview[0] != identifier or preview[1] != revision:
                raise RuleError("REVISION_CONFLICT")
            plan = self.plan(connection, identifier)
            if payload["confirm_name"] != plan["account_name"]:
                raise RuleError("CONFIRM_NAME_MISMATCH")
            reason = self.simulate(connection, plan)
            if reason:
                raise RuleError(reason)
            backup_path = self.backup()
            self.remove(connection, plan)
            self.accounting.audit(
                connection,
                identifier,
                "delete_account",
                None,
                {
                    "deleted": True,
                    "event_count": plan["event_count"],
                    "backup_file": backup_path.name,
                },
            )
            return {
                "deleted": True,
                "event_count": plan["event_count"],
                "backup_path": str(backup_path),
            }

        return self.accounting.command(key, "delete_account:" + identifier, payload, action)
