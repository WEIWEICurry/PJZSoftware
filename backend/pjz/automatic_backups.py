"""Local daily snapshots, isolated from business transactions and remote services."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import threading
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from pjz.storage import MAX_PACKAGE, DataError, LedgerStore, inspect_backup, write_verified_backup


class AutomaticBackups:
    retention = 14

    def __init__(
        self, store: LedgerStore, clock: Callable[[], datetime] = datetime.now, interval: float = 60
    ) -> None:
        self.store = store
        self.directory = store.directory / "backups" / "automatic"
        self.clock = clock
        self.interval = interval
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.worker: threading.Thread | None = None
        self.error: str | None = None
        self.validated: dict[str, tuple[int, int, dict[str, Any] | None]] = {}

    def _prepare(self) -> None:
        if (
            self.directory.parent.is_symlink()
            or self.directory.is_symlink()
            or self.directory.resolve() != self.directory
        ):
            raise DataError("BACKUP_UNSAFE_PATH")
        self.directory.mkdir(parents=True, exist_ok=True)

    def _read(self, path: Path) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise DataError("BACKUP_UNSAFE_PATH")
        with path.open("rb") as stream:
            payload = stream.read(MAX_PACKAGE + 1)
        inspect_backup(payload)
        return payload

    def _scan(self) -> tuple[list[dict[str, Any]], int]:
        self._prepare()
        files = []
        invalid = 0
        for path in sorted(self.directory.glob("daily-*.pjzbackup"), reverse=True):
            match = re.fullmatch(r"daily-(\d{4}-\d{2}-\d{2})\.pjzbackup", path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            try:
                datetime.strptime(match[1], "%Y-%m-%d")
                stat = path.stat()
                cached = self.validated.get(path.name)
                if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
                    metadata = cached[2]
                else:
                    with zipfile.ZipFile(io.BytesIO(self._read(path))) as package:
                        manifest = json.loads(package.read("manifest.json"))
                    if manifest["ledger_id"] != self.store.metadata()["id"]:
                        raise DataError("BACKUP_METADATA_MISMATCH")
                    metadata = {
                        "id": match[1],
                        "created_at": manifest["created_at"],
                        "revision": manifest["ledger_revision"],
                        "size": stat.st_size,
                    }
                    self.validated[path.name] = (stat.st_mtime_ns, stat.st_size, metadata)
                if metadata:
                    files.append(metadata)
                else:
                    invalid += 1
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                invalid += 1
        files.sort(key=lambda row: (row["revision"], row["created_at"]), reverse=True)
        return files, invalid

    def check(self, force: bool = False) -> None:
        with self.lock:
            try:
                files, invalid = self._scan()
                revision = self.store.metadata()["revision"]
                if force or not files or files[0]["revision"] != revision:
                    day = self.clock().date().isoformat()
                    destination = self.directory / f"daily-{day}.pjzbackup"
                    payload = self.store.backup()
                    inspect_backup(payload)
                    # Preserve the damaged bytes separately before publishing a replacement.
                    if destination.exists():
                        try:
                            self._read(destination)
                        except DataError:
                            if destination.is_symlink():
                                raise
                            destination.rename(
                                self.directory / ("damaged-" + uuid.uuid4().hex + ".pjzbackup")
                            )
                    write_verified_backup(destination, payload)
                    self.validated.pop(destination.name, None)
                    files, _ = self._scan()
                    for expired in files[self.retention :]:
                        path = self.directory / f"daily-{expired['id']}.pjzbackup"
                        self._read(path)
                        path.unlink()
                        self.validated.pop(path.name, None)
                self.error = None
            except (OSError, ValueError, sqlite3.Error, SQLAlchemyError):
                self.error = "AUTO_BACKUP_FAILED"

    def status(self) -> dict[str, Any]:
        with self.lock:
            try:
                files, invalid = self._scan()
            except (OSError, ValueError, sqlite3.Error, SQLAlchemyError):
                self.error = "AUTO_BACKUP_FAILED"
                files, invalid = [], 0
            current = self.store.metadata()["revision"]
            latest = files[0] if files else None
            return {
                "directory": str(self.directory),
                "retention": self.retention,
                "last_success_at": latest["created_at"] if latest else None,
                "last_revision": latest["revision"] if latest else None,
                "current_revision": current,
                "pending": latest is None or latest["revision"] != current,
                "error": self.error,
                "invalid_count": invalid,
                "files": files,
            }

    def download(self, identifier: str) -> bytes:
        with self.lock:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", identifier):
                raise DataError("BACKUP_NOT_FOUND")
            files, _ = self._scan()
            if identifier not in {row["id"] for row in files}:
                raise DataError("BACKUP_NOT_FOUND")
            try:
                return self._read(self.directory / f"daily-{identifier}.pjzbackup")
            except OSError:
                raise DataError("BACKUP_NOT_FOUND") from None

    def start(self) -> None:
        def run() -> None:
            self.check()
            while not self.stopping.wait(self.interval):
                self.check()

        self.worker = threading.Thread(target=run, name="local-daily-backup", daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.worker:
            self.worker.join()
        self.check()
