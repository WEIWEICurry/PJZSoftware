"""Transactional, source-preserving historical imports and reversible coverage."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from typing import Any

from sqlalchemy import Connection, text

from pjz.accounting import Accounting, fetch_all, now
from pjz.domain import RuleError
from pjz.history_domain import covered, event_amount, overlaps, parse_source


def active_summaries(connection: Connection) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT s.* FROM historical_summaries s JOIN import_batches b "
        "ON b.id=s.batch_id WHERE b.status='active'",
    )


class HistoryImports:
    def __init__(self, accounting: Accounting) -> None:
        self.accounting = accounting
        self.previews: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def keep(self, item: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.previews = {
                k: v for k, v in self.previews.items() if v["expires"] > time.monotonic()
            }
            if len(self.previews) >= 8:
                oldest = next(iter(self.previews))
                del self.previews[oldest]
            self.previews[token] = {**item, "expires": time.monotonic() + 600}
        return token

    def plan(
        self, connection: Connection, payload: bytes, mapping: dict[str, str]
    ) -> tuple[list[dict[str, Any]], str]:
        source, canonical_hash = parse_source(payload)
        if set(mapping) - {r["mapping_key"] for r in source}:
            raise RuleError("HISTORY_INVALID_MAPPING")
        categories = fetch_all(connection, "SELECT * FROM categories WHERE archived=0")
        by_id = {r["id"]: r for r in categories}
        existing = active_summaries(connection)
        duplicate = bool(
            fetch_all(
                connection,
                "SELECT id FROM import_batches WHERE status='active' "
                "AND (file_hash=:file OR canonical_hash=:canonical)",
                {"file": hashlib.sha256(payload).hexdigest(), "canonical": canonical_hash},
            )
        )
        events = fetch_all(connection, "SELECT * FROM financial_events WHERE status='active'")
        result: list[dict[str, Any]] = []
        for row in source:
            identifier = mapping.get(row["mapping_key"])
            if identifier is None:
                identifier = next(
                    (
                        c["id"]
                        for c in categories
                        if c["name"] == row["source_category"]
                        and c["direction"] == row["direction"]
                    ),
                    None,
                )
            category = by_id.get(identifier or "")
            if identifier and (not category or category["direction"] != row["direction"]):
                raise RuleError("HISTORY_INVALID_MAPPING")
            mapped = {
                **row,
                "category_id": identifier,
                "category_name": category["name"] if category else "",
                "status": "duplicate" if duplicate else "ready" if identifier else "unmapped",
            }
            if not duplicate and identifier:
                if any(overlaps(mapped, other) for other in existing):
                    mapped["status"] = "conflict"
                for other in result:
                    if overlaps(mapped, other):
                        mapped["status"] = other["status"] = "conflict"
            details = [e for e in events if covered(e, [mapped])]
            mapped["detail_count"] = len(details)
            mapped["detail_fen"] = str(sum(event_amount(e) for e in details))
            mapped["report_delta_fen"] = str(int(mapped["amount_fen"]) - int(mapped["detail_fen"]))
            mapped["amount_fen"] = str(mapped["amount_fen"])
            result.append(mapped)
        return result, canonical_hash

    def preview(self, payload: bytes, filename: str, mapping: dict[str, str]) -> dict[str, Any]:
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            rows, canonical_hash = self.plan(connection, payload, mapping)
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
        filename = filename.replace("\\", "/").split("/")[-1][:120] or "summary.json"
        complete_mapping = {r["mapping_key"]: r["category_id"] for r in rows if r["category_id"]}
        token = self.keep(
            {
                "action": "import",
                "payload": payload,
                "filename": filename,
                "mapping": complete_mapping,
                "revision": revision,
                "can_confirm": all(r["status"] == "ready" for r in rows),
            }
        )
        return {
            "preview_token": token,
            "action": "import",
            "filename": filename,
            "file_hash": hashlib.sha256(payload).hexdigest(),
            "canonical_hash": canonical_hash,
            "can_confirm": all(r["status"] == "ready" for r in rows),
            "rows": rows,
        }

    def commit(self, token: str, key: str) -> dict[str, Any]:
        def action(connection: Connection) -> dict[str, Any]:
            with self.lock:
                item = self.previews.get(token)
            if not item or item["expires"] <= time.monotonic():
                raise RuleError("PREVIEW_EXPIRED")
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
            if revision != item["revision"]:
                raise RuleError("REVISION_CONFLICT")
            if item["action"] == "withdraw":
                batch_id = item["batch_id"]
                before = fetch_all(
                    connection, "SELECT * FROM import_batches WHERE id=:id", {"id": batch_id}
                )[0]
                if before["status"] != "active":
                    raise RuleError("REVISION_CONFLICT")
                connection.execute(
                    text(
                        "UPDATE import_batches SET status='withdrawn',revision=revision+1 "
                        "WHERE id=:id"
                    ),
                    {"id": batch_id},
                )
                self.accounting.audit(
                    connection, batch_id, "withdraw_import", None, {"status": "withdrawn"}
                )
                return {"id": batch_id, "status": "withdrawn"}
            if not item["can_confirm"]:
                raise RuleError("HISTORY_CONFLICT")
            rows, canonical_hash = self.plan(connection, item["payload"], item["mapping"])
            if not all(r["status"] == "ready" for r in rows):
                raise RuleError("HISTORY_CONFLICT")
            batch_id = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO import_batches (id,ledger_id,filename,file_hash,canonical_hash,"
                    "source_blob,"
                    "mapping_json,status,created_at) VALUES (:id,(SELECT id FROM ledger),:filename,"
                    ":file,:canonical,:source,:mapping,'active',:at)"
                ),
                {
                    "id": batch_id,
                    "filename": item["filename"],
                    "file": hashlib.sha256(item["payload"]).hexdigest(),
                    "canonical": canonical_hash,
                    "source": item["payload"],
                    "mapping": json.dumps(item["mapping"], ensure_ascii=False),
                    "at": now(),
                },
            )
            for row in rows:
                connection.execute(
                    text(
                        "INSERT INTO historical_summaries VALUES "
                        "(:id,:batch,:period_start,:period_end,"
                        ":direction,:category_id,:source_category,:amount,:refs)"
                    ),
                    {
                        **row,
                        "id": str(uuid.uuid4()),
                        "batch": batch_id,
                        "amount": int(row["amount_fen"]),
                        "refs": json.dumps(row["source_refs"], ensure_ascii=False),
                    },
                )
            self.accounting.audit(
                connection,
                batch_id,
                "import_history",
                None,
                {"row_count": len(rows), "file_hash": hashlib.sha256(item["payload"]).hexdigest()},
            )
            return {"id": batch_id, "status": "active"}

        # Receipt lookup precedes token expiry/version checking, preserving lost-response retry.
        return self.accounting.command(key, "history_commit", {"preview_token": token}, action)

    def batches(self) -> list[dict[str, Any]]:
        with self.accounting.engine.connect() as connection:
            return fetch_all(
                connection,
                "SELECT id,filename,file_hash,canonical_hash,status,revision,created_at "
                "FROM import_batches ORDER BY created_at DESC,id",
            )

    def detail(self, identifier: str) -> dict[str, Any]:
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            batches = fetch_all(
                connection,
                "SELECT id,filename,file_hash,canonical_hash,status,revision,created_at "
                "FROM import_batches WHERE id=:id",
                {"id": identifier},
            )
            if not batches:
                raise RuleError("HISTORY_BATCH_NOT_FOUND")
            rows = fetch_all(
                connection,
                "SELECT s.*,c.name AS category_name FROM historical_summaries s "
                "JOIN categories c ON c.id=s.category_id WHERE batch_id=:id "
                "ORDER BY period_start,direction,source_category",
                {"id": identifier},
            )
            events = fetch_all(connection, "SELECT * FROM financial_events WHERE status='active'")
            for row in rows:
                row["amount_fen"] = str(row["amount_fen"])
                row["source_refs"] = json.loads(row.pop("source_refs_json"))
                row["mapping_key"] = row["direction"] + ":" + row["source_category"]
                details = [e for e in events if covered(e, [row])]
                row["detail_count"] = len(details)
                row["detail_fen"] = str(sum(event_amount(e) for e in details))
                row["report_delta_fen"] = str(int(row["amount_fen"]) - int(row["detail_fen"]))
                row["status"] = "ready"
            return {**batches[0], "rows": rows}

    def withdrawal_preview(self, identifier: str) -> dict[str, Any]:
        # Both detail and revision must belong to one snapshot: reject any intervening write.
        with self.accounting.engine.connect() as connection:
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
        detail = self.detail(identifier)
        if detail["status"] != "active":
            raise RuleError("REVISION_CONFLICT")
        for row in detail["rows"]:
            row["report_delta_fen"] = str(-int(row["report_delta_fen"]))
        token = self.keep({"action": "withdraw", "batch_id": identifier, "revision": revision})
        return {**detail, "preview_token": token, "action": "withdraw", "can_confirm": True}

    @staticmethod
    def verify(connection: Connection) -> None:
        """A backup must prove the stored facts still match its original source and mapping."""
        categories = {r["id"]: r for r in fetch_all(connection, "SELECT * FROM categories")}
        for batch in fetch_all(connection, "SELECT * FROM import_batches"):
            source, digest = parse_source(batch["source_blob"])
            if (
                hashlib.sha256(batch["source_blob"]).hexdigest() != batch["file_hash"]
                or digest != batch["canonical_hash"]
            ):
                raise RuleError("HISTORY_INVALID_DATA")
            mapping = json.loads(batch["mapping_json"])
            expected = []
            for row in source:
                category_id = mapping[row["mapping_key"]]
                if categories[category_id]["direction"] != row["direction"]:
                    raise RuleError("HISTORY_INVALID_DATA")
                expected.append(
                    (
                        row["period_start"],
                        row["period_end"],
                        row["direction"],
                        category_id,
                        row["source_category"],
                        row["amount_fen"],
                        json.dumps(row["source_refs"], ensure_ascii=False),
                    )
                )
            actual = [
                tuple(
                    row[k]
                    for k in (
                        "period_start",
                        "period_end",
                        "direction",
                        "category_id",
                        "source_category",
                        "amount_fen",
                        "source_refs_json",
                    )
                )
                for row in fetch_all(
                    connection,
                    "SELECT * FROM historical_summaries WHERE batch_id=:id",
                    {"id": batch["id"]},
                )
            ]
            if sorted(expected) != sorted(actual):
                raise RuleError("HISTORY_INVALID_DATA")
        active = active_summaries(connection)
        for index, row in enumerate(active):
            if any(overlaps(row, other) for other in active[index + 1 :]):
                raise RuleError("HISTORY_INVALID_DATA")
