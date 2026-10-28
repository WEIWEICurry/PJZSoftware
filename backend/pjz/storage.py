"""Versioned M0 database and verified snapshot backups; no personal fixtures."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text

SCHEMA_VERSION = 6
SUPPORTED_SCHEMAS = (1, 2, 3, 4, 5, 6)
MAX_PACKAGE = 8 * 1024 * 1024


class DataError(ValueError):
    pass


class LedgerStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ledger.sqlite3"
        existing = self.path.exists()
        self.engine = create_engine(
            "sqlite:///" + self.path.as_posix(),
            connect_args={"timeout": 10},
        )

        @event.listens_for(self.engine, "connect")
        def configure_connection(connection: sqlite3.Connection, record: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

        if existing:
            validate_database(self.path)
        else:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE ledger (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                        "revision INTEGER NOT NULL CHECK(revision > 0), created_at TEXT NOT NULL)"
                    )
                )
                connection.execute(
                    text("INSERT INTO ledger VALUES (:id, :name, 1, :created)"),
                    {
                        "id": str(uuid.uuid4()),
                        "name": "我的本地账本",
                        "created": datetime.now(UTC).isoformat(),
                    },
                )
                connection.execute(text("PRAGMA user_version=1"))
        with self.engine.connect() as connection:
            version = connection.execute(text("PRAGMA user_version")).scalar_one()
        if version < SCHEMA_VERSION:
            if existing:
                backup_dir = self.directory / "backups"
                backup_dir.mkdir(exist_ok=True)
                payload = self.backup()
                inspect_backup(payload)
                (
                    backup_dir
                    / ("before-v" + str(SCHEMA_VERSION) + "-" + uuid.uuid4().hex + ".pjzbackup")
                ).write_bytes(payload)
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
            with self.engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    config.attributes["connection"] = connection
                    if version == 1:
                        command.stamp(config, "0001")
                    command.upgrade(config, "head")
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                        raise DataError("INVALID_DATABASE")
                    from pjz.accounting import Accounting

                    Accounting(self.engine).rebuild(connection, persist=False)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    self.engine.dispose()
                    raise
                finally:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.commit()
        from pjz.accounting import Accounting

        Accounting(self.engine).seed_categories()
        with self.engine.connect() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))

    def metadata(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM ledger")).mappings().one()
            return dict(row)

    def rename(self, name: str, revision: int) -> dict[str, Any]:
        with self.engine.begin() as connection:
            result = connection.execute(
                text("UPDATE ledger SET name=:name, revision=revision+1 WHERE revision=:revision"),
                {"name": name, "revision": revision},
            )
            if result.rowcount != 1:
                raise DataError("REVISION_CONFLICT")
        return self.metadata()

    def backup(self) -> bytes:
        # SQLite's backup API includes committed WAL state, unlike copying a live file.
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "ledger.sqlite3"
            with (
                closing(sqlite3.connect(self.path)) as source,
                closing(sqlite3.connect(snapshot)) as target,
            ):
                source.backup(target)
            # Rebuild the snapshot, not the live ledger, so free pages do not carry old text.
            with closing(sqlite3.connect(snapshot)) as compacted:
                compacted.execute("VACUUM")
            validate_database(snapshot)
            payload = snapshot.read_bytes()
        manifest = {
            "format_version": 1,
            "schema_version": database_version(self.path),
            "created_at": datetime.now(UTC).isoformat(),
            "ledger_id": self.metadata()["id"],
            "files": {
                "ledger.sqlite3": {
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            },
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("manifest.json", json.dumps(manifest))
            package.writestr("ledger.sqlite3", payload)
        return output.getvalue()

    def restore(self, payload: bytes) -> Path:
        snapshot = inspect_backup(payload)
        destination = self.directory.parent / ("restored-" + uuid.uuid4().hex)
        # Preserve the current ledger before creating a separate restored ledger.
        backup_dir = self.directory / "backups"
        backup_dir.mkdir(exist_ok=True)
        safety = backup_dir / (uuid.uuid4().hex + ".pjzbackup")
        safety.write_bytes(self.backup())
        with tempfile.TemporaryDirectory(dir=self.directory.parent) as temporary:
            staged = Path(temporary) / "restored"
            staged.mkdir()
            (staged / "ledger.sqlite3").write_bytes(snapshot)
            validate_database(staged / "ledger.sqlite3")
            restored = LedgerStore(staged)
            restored.close()
            validate_database(staged / "ledger.sqlite3")
            staged.rename(destination)
        return destination

    def close(self) -> None:
        self.engine.dispose()


def validate_database(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in SUPPORTED_SCHEMAS:
                raise DataError("UNSUPPORTED_SCHEMA")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DataError("INVALID_DATABASE")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise DataError("INVALID_DATABASE")
            objects = connection.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            expected_tables = (
                {"ledger"}
                if version == 1
                else {
                    "ledger",
                    "alembic_version",
                    "accounts",
                    "categories",
                    "financial_events",
                    "cash_entries",
                    "operation_revisions",
                    "idempotency_records",
                }
            )
            if version >= 4:
                expected_tables.update({"import_batches", "historical_summaries"})
            if version >= 5:
                expected_tables.add("category_budgets")
            if version >= 6:
                expected_tables.update({"instruments", "investment_events", "valuations"})
            tables = {name for kind, name in objects if kind == "table"}
            if tables != expected_tables or any(
                kind not in ("table", "index") for kind, _ in objects
            ):
                raise DataError("UNSUPPORTED_DATABASE")
            if version >= 2:
                if connection.execute("SELECT version_num FROM alembic_version").fetchall() != [
                    (f"{version:04d}",)
                ]:
                    raise DataError("UNSUPPORTED_SCHEMA")
            rows = connection.execute(
                "SELECT id, name, revision, created_at FROM ledger"
            ).fetchall()
            if len(rows) != 1 or not isinstance(rows[0][1], str) or rows[0][2] < 1:
                raise DataError("INVALID_DATABASE")
            uuid.UUID(rows[0][0])
        if version >= 2:
            from pjz.accounting import Accounting
            from pjz.domain import RuleError

            verifier = create_engine(
                "sqlite://", creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            )
            try:
                with verifier.connect() as check:
                    check.exec_driver_sql("BEGIN")
                    Accounting(verifier).rebuild(check, persist=False)
                    if version >= 4:
                        from pjz.history import HistoryImports

                        HistoryImports.verify(check)
                    if version >= 5:
                        from pjz.budgets import Budgets

                        Budgets.verify(check)
            except RuleError as error:
                raise DataError("INVALID_ACCOUNTING_DATA") from error
            finally:
                verifier.dispose()
    except (sqlite3.Error, ValueError, TypeError, IndexError, KeyError, AttributeError) as error:
        if isinstance(error, DataError):
            raise
        raise DataError("INVALID_DATABASE") from error


def inspect_backup(payload: bytes) -> bytes:
    if len(payload) > MAX_PACKAGE:
        raise DataError("BACKUP_TOO_LARGE")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as package:
            entries = package.infolist()
            if sorted(entry.filename for entry in entries) != ["ledger.sqlite3", "manifest.json"]:
                raise DataError("INVALID_BACKUP_FILES")
            if any(entry.file_size > MAX_PACKAGE or entry.flag_bits & 1 for entry in entries):
                raise DataError("BACKUP_TOO_LARGE")
            manifest = json.loads(package.read("manifest.json"))
            if (
                manifest["format_version"] != 1
                or manifest["schema_version"] not in SUPPORTED_SCHEMAS
            ):
                raise DataError("UNSUPPORTED_BACKUP")
            snapshot = package.read("ledger.sqlite3")
            descriptor = manifest["files"]["ledger.sqlite3"]
            if len(snapshot) != descriptor["size"]:
                raise DataError("BACKUP_CHECKSUM_FAILED")
            if hashlib.sha256(snapshot).hexdigest() != descriptor["sha256"]:
                raise DataError("BACKUP_CHECKSUM_FAILED")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.sqlite3"
            path.write_bytes(snapshot)
            validate_database(path)
            if database_version(path) != manifest["schema_version"]:
                raise DataError("BACKUP_SCHEMA_MISMATCH")
        return snapshot
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, OSError) as error:
        if isinstance(error, DataError):
            raise
        raise DataError("INVALID_BACKUP") from error


def database_version(path: Path) -> int:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
