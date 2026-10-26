"""Exercise the actual packaged launcher without Node/Python on child PATH."""

import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

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
print("PASS: packaged assets/minimal PATH/loopback/auth/duplicate launch/crash recovery")
