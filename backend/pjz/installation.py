"""Verified local releases and stable dispatch; no financial or HTTP dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from filelock import FileLock

MAX_RELEASE = 1024 * 1024 * 1024
MAX_FILES = 6000


class InstallError(ValueError):
    pass


def matching_instance(metadata: dict[str, Any], version: str, executable: Path) -> bool:
    """A stale metadata file must never make a legacy process look like the new version."""
    if metadata.get("version") != version or metadata.get("executable") != str(
        executable.resolve()
    ):
        return False
    pid = metadata.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    expected_images = {executable.resolve()}
    if not getattr(sys, "frozen", False) and executable.resolve() == Path(sys.executable).resolve():
        expected_images.add(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            return (
                bool(kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)))
                and Path(buffer.value).resolve() in expected_images
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        return Path(f"/proc/{pid}/exe").resolve(strict=True) in expected_images
    except OSError:
        return False


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".pending-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        raise InstallError("INVALID_INSTALLATION")
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise InstallError("INVALID_INSTALLATION")
    return value


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not (
        path.is_absolute()
        or "\\" in name
        or ":" in name
        or any(part in ("..", ".", "") for part in name.split("/"))
        or any(part.rstrip(" .") != part for part in path.parts)
        or any(
            re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in path.parts
        )
    )


def verify_release(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    manifest = read_json(directory / "release.json")
    files = manifest.get("files")
    if (
        manifest.get("format") != 1
        or manifest.get("protocol") != 1
        or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))
        or type(manifest.get("schema")) is not int
        or not isinstance(files, dict)
        or not 3 <= len(files) <= MAX_FILES
    ):
        raise InstallError("INVALID_RELEASE")
    if not {"PJZSoftware.exe", "PJZStart.exe", "_internal/frontend/index.html"} <= files.keys():
        raise InstallError("INVALID_RELEASE")
    actual = set()
    total = 0
    for path in directory.rglob("*"):
        if path.is_symlink() or path.resolve().is_relative_to(directory) is False:
            raise InstallError("INVALID_RELEASE")
        if path.is_file() and path != directory / "release.json":
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(files) or len({name.casefold() for name in files}) != len(files):
        raise InstallError("INVALID_RELEASE")
    for name, descriptor in files.items():
        if not safe_name(name) or not isinstance(descriptor, dict):
            raise InstallError("INVALID_RELEASE")
        path = directory / name
        size = path.stat().st_size
        total += size
        if total > MAX_RELEASE or size != descriptor.get("size"):
            raise InstallError("INVALID_RELEASE")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != descriptor.get("sha256"):
                raise InstallError("RELEASE_CHECKSUM_FAILED")
    return manifest


def extract_release(package: Path, destination: Path) -> Path:
    if package.stat().st_size > 512 * 1024 * 1024:
        raise InstallError("RELEASE_TOO_LARGE")
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries if not entry.is_dir()]
        if (
            len(entries) > MAX_FILES + 100
            or sum(e.file_size for e in entries) > MAX_RELEASE
            or len(names) != len({name.casefold() for name in names})
        ):
            raise InstallError("INVALID_RELEASE")
        for entry in entries:
            if entry.orig_filename != entry.filename:
                raise InstallError("INVALID_RELEASE")
            name = entry.filename.rstrip("/")
            if (
                not safe_name(name)
                or not name.startswith("PJZSoftware/")
                or entry.flag_bits & 1
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise InstallError("INVALID_RELEASE")
        for entry in entries:
            target = destination / entry.filename
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
    root = destination / "PJZSoftware"
    verify_release(root)
    return root


def target_path(root: Path, target: dict[str, Any]) -> Path:
    slot = target.get("slot")
    ledger = target.get("ledger_directory")
    if (
        not isinstance(slot, str)
        or not re.fullmatch(r"\d+\.\d+\.\d+-[a-f0-9]{32}", slot)
        or not isinstance(ledger, str)
        or not Path(ledger).is_absolute()
    ):
        raise InstallError("INVALID_INSTALLATION")
    path = root / "versions" / slot
    if path.resolve() != path or not (Path(ledger) / "ledger.sqlite3").is_file():
        raise InstallError("INVALID_INSTALLATION")
    return path


def current_state(root: Path) -> dict[str, Any]:
    state = read_json(root / "current.json")
    if state.get("format") != 1:
        raise InstallError("INVALID_INSTALLATION")
    target_path(root, state["active"])
    if state.get("previous"):
        target_path(root, state["previous"])
    return state


def stage_release(source: Path, root: Path, schema: int) -> str:
    root = root.resolve()
    manifest = verify_release(source)
    if manifest["schema"] != schema:
        raise InstallError("UPDATE_SCHEMA_MISMATCH")
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    if versions.resolve() != versions:
        raise InstallError("INVALID_INSTALLATION")
    slot = manifest["version"] + "-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=versions, prefix=".staging-") as temporary:
        staged = Path(temporary) / "release"
        shutil.copytree(source, staged)
        verify_release(staged)
        staged.rename(versions / slot)
    return str(slot)


def queue_transition(root: Path, target: dict[str, Any], expected: dict[str, Any]) -> None:
    if current_state(root) != expected:
        raise InstallError("INSTALLATION_CHANGED")
    target_path(root, target)
    atomic_json(root / "pending.json", {"expected": expected, "target": target})


def start_target(
    root: Path, target: dict[str, Any], headless: bool, no_browser: bool
) -> subprocess.Popen[bytes] | None:
    release = target_path(root, target)
    manifest = verify_release(release)
    identifier = uuid.uuid4().hex
    ready = root / "ready" / (identifier + ".json")
    args = [
        str(release / "PJZSoftware.exe"),
        "--data-dir",
        target["ledger_directory"],
        "--managed-root",
        str(root),
        "--ready-id",
        identifier,
    ]
    if headless:
        args.append("--headless")
    if no_browser:
        args.append("--no-browser")
    process = subprocess.Popen(
        args, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if ready.exists():
                message = read_json(ready)
                if message == {
                    "pid": process.pid,
                    "version": manifest["version"],
                    "id": identifier,
                }:
                    return process
                raise InstallError("INVALID_STARTUP_HANDSHAKE")
            if process.poll() is not None:
                if process.returncode == 0:
                    return None  # Same-version duplicate was handled by the running service.
                raise InstallError("UPDATE_START_FAILED")
            time.sleep(0.05)
        raise InstallError("UPDATE_START_TIMEOUT")
    except Exception:
        if process.poll() is None:
            process.terminate()  # Only the child we just started, never an existing service.
            process.wait(timeout=10)
        raise
    finally:
        ready.unlink(missing_ok=True)


def dispatch(root: Path, headless: bool = False, no_browser: bool = False) -> str | None:
    root = root.resolve()
    with FileLock(root / "manager.lock", timeout=0):
        state = current_state(root)
        pending_path = root / "pending.json"
        if not pending_path.exists():
            start_target(root, state["active"], headless, no_browser)
            return None
        child = None
        committed = False
        try:
            pending = read_json(pending_path)
            if pending.get("target") == state["active"]:
                pending_path.unlink()
                start_target(root, state["active"], headless, no_browser)
                return None
            if pending.get("expected") != state:
                raise InstallError("INSTALLATION_CHANGED")
            target = pending["target"]
            old_manifest = verify_release(target_path(root, state["active"]))
            new_manifest = verify_release(target_path(root, target))
            if old_manifest["schema"] != new_manifest["schema"]:
                raise InstallError("UPDATE_SCHEMA_MISMATCH")
            child = start_target(root, target, headless, no_browser)
            if child is None:
                raise InstallError("UPDATE_START_FAILED")
            atomic_json(
                root / "current.json", {"format": 1, "active": target, "previous": state["active"]}
            )
            committed = True
            pending_path.unlink()
            return None
        except (OSError, ValueError, KeyError) as error:
            code = str(error) if isinstance(error, InstallError) else "UPDATE_START_FAILED"
            if committed:
                # A leftover pending file is recognized as already committed on next launch.
                return None
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
            if pending_path.exists():
                try:
                    pending_path.rename(root / ("failed-" + uuid.uuid4().hex + ".json"))
                except OSError:
                    # Still reopen the known current version if failed-candidate cleanup is denied.
                    code = "UPDATE_START_FAILED"
            start_target(root, state["active"], headless, no_browser)
            return code
