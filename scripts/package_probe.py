"""Exercise the actual packaged launcher without Node/Python on child PATH."""

import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from pjz import __version__
from pjz.installation import (
    atomic_json,
    current_state,
    matching_instance,
    stage_release,
    verify_release,
)
from pjz.launch_management import LaunchManagement
from pjz.storage import SCHEMA_VERSION, LedgerStore

executable = Path("dist/PJZSoftware/PJZSoftware.exe").resolve()
environment = dict(os.environ)
environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
environment.pop("PYTHONPATH", None)
environment.pop("PYTHONHOME", None)
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
subprocess.run(
    [str(executable), "--self-test"], env=environment, check=True, creationflags=flags, timeout=40
)

with tempfile.TemporaryDirectory(prefix="PJZ-launch-中文-") as temporary:
    directory = Path(temporary) / "账本"
    process = subprocess.Popen(
        [str(executable), "--headless", "--no-browser", "--data-dir", str(directory)],
        env=environment,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 20
        endpoint = None
        while time.monotonic() < deadline:
            assert process.poll() is None, "Packaged launcher exited early"
            output = subprocess.check_output(
                [
                    str(Path(os.environ["SystemRoot"]) / "System32" / "netstat.exe"),
                    "-ano",
                    "-p",
                    "TCP",
                ],
                text=True,
                creationflags=flags,
            )
            for line in output.splitlines():
                parts = line.split()
                if len(parts) == 5 and parts[-1] == str(process.pid) and parts[3] == "LISTENING":
                    assert parts[1].startswith("127.0.0.1:"), "Non-loopback bind"
                    endpoint = "http://" + parts[1]
            if endpoint:
                break
            time.sleep(0.1)
        assert endpoint, "No loopback listener"
        with urllib.request.urlopen(endpoint + "/health", timeout=5) as response:
            assert response.status == 200
        with urllib.request.urlopen(endpoint + "/", timeout=5) as response:
            assert b"PJZSoftware" in response.read()
            policy = response.headers["Content-Security-Policy"]
            assert "'sha256-" in policy
        try:
            urllib.request.urlopen(endpoint + "/api/v1/ledger", timeout=5)
            raise AssertionError("Anonymous ledger access")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        deadline = time.monotonic() + 10
        automatic = directory / "backups" / "automatic"
        while not list(automatic.glob("daily-*.pjzbackup")) and time.monotonic() < deadline:
            time.sleep(0.05)
        from pjz.storage import inspect_backup

        daily = list(automatic.glob("daily-*.pjzbackup"))
        assert len(daily) == 1, "Packaged automatic backup missing"
        inspect_backup(daily[0].read_bytes())
        subprocess.run(
            [str(executable), "--headless", "--no-browser", "--data-dir", str(directory)],
            env=environment,
            creationflags=flags,
            check=True,
            timeout=10,
        )
        assert process.poll() is None, "Duplicate launch killed original"
        deadline = time.monotonic() + 5
        while (directory / "reopen.request").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not (directory / "reopen.request").exists(), "Reopen signal not consumed"
    finally:
        # This synthetic headless process has no credential on disk; terminate deliberately
        # to verify crash recovery, then reopen its database in the probe process.
        process.terminate()
        process.wait(timeout=10)
    from pjz.storage import LedgerStore

    store = LedgerStore(directory)
    assert store.metadata()["revision"] == 1
    store.close()
print(
    "PASS: packaged assets/minimal PATH/loopback/auth/automatic backup/"
    "duplicate launch/crash recovery"
)


# Real fixed launcher, isolated from the user's profile and desktop.
with tempfile.TemporaryDirectory(prefix="PJZ-fixed-entry-中文-") as temporary:
    home = Path(temporary).resolve()
    root = home / "application"
    book = home / "ledger"
    ledger = LedgerStore(book)
    ledger.close()
    source = executable.parent
    verify_release(source)
    slot = stage_release(source, root, SCHEMA_VERSION)
    shutil.copyfile(source / "PJZStart.exe", root / "PJZStart.exe")
    state = {"format": 1, "active": {"slot": slot, "ledger_directory": str(book)}, "previous": None}
    atomic_json(root / "current.json", state)

    owned_books = {book}

    def stop_owned() -> None:
        for owned_book in owned_books:
            stop_book(owned_book)

    def stop_book(owned_book: Path) -> None:
        runtime = owned_book / "runtime.json"
        if not runtime.exists():
            return
        import json

        metadata = json.loads(runtime.read_text("utf-8"))
        image = Path(metadata["executable"])
        assert image.resolve().is_relative_to((root / "versions").resolve())
        if matching_instance(metadata, __version__, image):
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x100000, False, metadata["pid"])
            assert handle, "Cannot wait on owned child"
            try:
                subprocess.run(
                    [
                        str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                        "/PID",
                        str(metadata["pid"]),
                        "/F",
                    ],
                    check=True,
                    capture_output=True,
                    creationflags=flags,
                    timeout=10,
                )
                assert kernel.WaitForSingleObject(handle, 10000) == 0, "Owned child has not exited"
            finally:
                kernel.CloseHandle(handle)

    def start_fixed() -> None:
        subprocess.run(
            [str(root / "PJZStart.exe"), "--headless", "--no-browser"],
            check=True,
            env=environment,
            creationflags=flags,
            timeout=60,
        )
        import json

        selected = current_state(root)["active"]
        runtime = Path(selected["ledger_directory"]) / "runtime.json"
        metadata = json.loads(runtime.read_text("utf-8"))
        assert matching_instance(metadata, __version__, Path(metadata["executable"]))

    try:
        start_fixed()
        start_fixed()  # Same-version duplicate reopens; no second writer.
        stop_owned()
        second = stage_release(source, root, SCHEMA_VERSION)
        ledger = LedgerStore(book)
        manager = LaunchManagement(book, root)
        manager.transition = root, {**state["active"], "slot": second}, state
        manager.finalize(ledger)
        ledger.close()
        start_fixed()
        updated = current_state(root)
        assert updated["active"]["slot"] == second and updated["previous"] == state["active"]
        stop_owned()
        broken = stage_release(source, root, SCHEMA_VERSION)
        with (root / "versions" / broken / "PJZSoftware.exe").open("ab") as stream:
            stream.write(b"synthetic corruption")
        ledger = LedgerStore(book)
        manager.transition = root, {**updated["active"], "slot": broken}, updated
        manager.finalize(ledger)
        ledger.close()
        start_fixed()
        assert current_state(root) == updated
        assert list(root.glob("failed-*.json")), "Failed candidate was not retained"
        stop_owned()
        ledger = LedgerStore(book)
        old = ledger.backup()
        ledger.rename("Synthetic original after backup", ledger.metadata()["revision"])
        destination = ledger.restore(old)
        owned_books.add(destination)
        manager.prepare_switch(destination)
        manager.finalize(ledger)
        ledger.close()
        start_fixed()
        assert current_state(root)["active"]["ledger_directory"] == str(destination)
        stop_owned()
        original = LedgerStore(book)
        assert original.metadata()["name"] == "Synthetic original after backup"
        original.close()
    finally:
        stop_owned()
print("PASS: fixed entry/managed readiness/local update/failure fallback/restored copy switch")
