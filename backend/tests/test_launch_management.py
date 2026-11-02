"""Synthetic release, pointer, startup and recovery authorization acceptance."""

import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pjz import __version__
from pjz.installation import (
    InstallError,
    atomic_json,
    current_state,
    dispatch,
    extract_release,
    queue_transition,
    stage_release,
    start_target,
    verify_release,
)
from pjz.launch_management import LaunchManagement
from pjz.storage import SCHEMA_VERSION, LedgerStore, inspect_backup
from test_foundation import authenticate


def release(path, version="0.16.0", schema=SCHEMA_VERSION):
    files = {
        "PJZSoftware.exe": b"synthetic-main",
        "PJZStart.exe": b"synthetic-starter",
        "_internal/frontend/index.html": b"<html>synthetic</html>",
    }
    for name, payload in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    atomic_json(
        path / "release.json",
        {
            "format": 1,
            "protocol": 1,
            "version": version,
            "schema": schema,
            "files": {
                name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in files.items()
            },
        },
    )
    return path


def archive_release(source, target):
    with zipfile.ZipFile(target, "w") as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, "PJZSoftware/" + path.relative_to(source).as_posix())
    return target


@pytest.fixture
def installed(tmp_path):
    store = LedgerStore(tmp_path / "合成账本")
    root = tmp_path / "固定入口"
    source = release(tmp_path / "release")
    slot = stage_release(source, root, SCHEMA_VERSION)
    state = {
        "format": 1,
        "active": {"slot": slot, "ledger_directory": str(store.directory)},
        "previous": None,
    }
    atomic_json(root / "current.json", state)
    yield store, root, source, state
    store.close()


def test_manifest_exact_files_integrity_and_zip_roundtrip(tmp_path):
    source = release(tmp_path / "source")
    assert verify_release(source)["version"] == "0.16.0"
    package = archive_release(source, tmp_path / "release.zip")
    extracted = extract_release(package, tmp_path / "output")
    assert verify_release(extracted) == verify_release(source)
    (source / "PJZSoftware.exe").write_bytes(b"synthetic-evil")
    with pytest.raises(InstallError):
        verify_release(source)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "PJZSoftware/../../outside",
        "/outside",
        "PJZSoftware/x\\y",
        "PJZSoftware/C:/x",
        "PJZSoftware/NUL",
        "PJZSoftware/x.",
        "PJZSoftware/x ",
    ],
)
def test_zip_paths_are_rejected_without_writing(tmp_path, name):
    package = tmp_path / "bad.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(name, b"bad")
    if "\\" in name:
        package.write_bytes(package.read_bytes().replace(b"PJZSoftware/x/y", b"PJZSoftware/x\\y"))
    with pytest.raises(InstallError):
        extract_release(package, tmp_path / "output")
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("kind", ["collision", "symlink", "oversize", "extra", "missing"])
def test_release_rejects_ambiguous_and_incomplete_files(tmp_path, monkeypatch, kind):
    source = release(tmp_path / "source")
    package = archive_release(source, tmp_path / "release.zip")
    if kind in ("collision", "symlink"):
        with zipfile.ZipFile(package, "a") as archive:
            entry = zipfile.ZipInfo(
                "PJZSoftware/pjzsoftware.exe" if kind == "collision" else "PJZSoftware/link"
            )
            if kind == "symlink":
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, b"link")
    elif kind == "oversize":
        monkeypatch.setattr("pjz.installation.MAX_RELEASE", 2)
    elif kind == "extra":
        with zipfile.ZipFile(package, "a") as archive:
            archive.writestr("PJZSoftware/extra.exe", b"extra")
    else:
        (source / "PJZStart.exe").unlink()
        package = archive_release(source, tmp_path / "missing.zip")
    with pytest.raises((InstallError, FileNotFoundError)):
        extract_release(package, tmp_path / "output")


def test_staging_failure_never_changes_current_or_source(installed, monkeypatch):
    _, root, source, state = installed

    def fail(*a, **kw):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("pjz.installation.shutil.copytree", fail)
    with pytest.raises(OSError):
        stage_release(source, root, SCHEMA_VERSION)
    assert current_state(root) == state
    assert verify_release(source)
    assert len(list((root / "versions").iterdir())) == 1


def test_schema_mismatch_and_pointer_path_rejected(installed, tmp_path):
    _, root, _, state = installed
    source = release(tmp_path / "future", schema=SCHEMA_VERSION + 1)
    with pytest.raises(InstallError, match="UPDATE_SCHEMA_MISMATCH"):
        stage_release(source, root, SCHEMA_VERSION)
    bad = {**state["active"], "slot": "../outside"}
    with pytest.raises(InstallError):
        queue_transition(root, bad, state)
    assert not (root / "pending.json").exists()


def test_failed_update_keeps_pointer_and_falls_back(installed, monkeypatch):
    _, root, source, state = installed
    slot = stage_release(source, root, SCHEMA_VERSION)
    target = {**state["active"], "slot": slot}
    queue_transition(root, target, state)
    calls = []

    def launch(root, selected, *args):
        calls.append(selected)
        if selected == target:
            raise InstallError("UPDATE_START_FAILED")
        return MagicMock()

    monkeypatch.setattr("pjz.installation.start_target", launch)
    assert dispatch(root) == "UPDATE_START_FAILED"
    assert calls == [target, state["active"]]
    assert current_state(root) == state
    assert len(list(root.glob("failed-*.json"))) == 1


@pytest.mark.parametrize("commit_fails", [False, True])
def test_new_pointer_requires_ready_and_atomic_commit(installed, monkeypatch, commit_fails):
    _, root, source, state = installed
    target = {**state["active"], "slot": stage_release(source, root, SCHEMA_VERSION)}
    queue_transition(root, target, state)
    child = MagicMock()
    child.poll.return_value = None
    starts = MagicMock(return_value=child)
    monkeypatch.setattr("pjz.installation.start_target", starts)
    if commit_fails:
        monkeypatch.setattr(
            "pjz.installation.atomic_json", lambda *a: (_ for _ in ()).throw(OSError())
        )
    result = dispatch(root)
    if commit_fails:
        assert result == "UPDATE_START_FAILED"
        assert current_state(root) == state
        child.terminate.assert_called_once()
        assert starts.call_args_list[-1].args[1] == state["active"]
    else:
        assert result is None
        assert current_state(root)["active"] == target
        assert current_state(root)["previous"] == state["active"]
        child.terminate.assert_not_called()


def test_ready_handshake_requires_correct_pid_version_and_nonce(installed, monkeypatch):
    _, root, _, state = installed
    process = MagicMock(pid=1234)
    process.poll.return_value = None

    def spawn(args, **kwargs):
        nonce = args[args.index("--ready-id") + 1]
        atomic_json(
            root / "ready" / (nonce + ".json"), {"pid": 999, "id": nonce, "version": "0.16.0"}
        )
        return process

    monkeypatch.setattr("pjz.installation.subprocess.Popen", spawn)
    with pytest.raises(InstallError, match="INVALID_STARTUP_HANDSHAKE"):
        start_target(root, state["active"], True, True)
    process.terminate.assert_called_once()


def test_successful_handshake_and_duplicate(installed, monkeypatch):
    _, root, _, state = installed
    process = MagicMock(pid=1234)
    process.poll.return_value = None

    def spawn(args, **kwargs):
        nonce = args[args.index("--ready-id") + 1]
        atomic_json(
            root / "ready" / (nonce + ".json"), {"pid": 1234, "id": nonce, "version": "0.16.0"}
        )
        return process

    monkeypatch.setattr("pjz.installation.subprocess.Popen", spawn)
    assert start_target(root, state["active"], True, True) is process
    process.terminate.assert_not_called()
    monkeypatch.setattr("pjz.installation.subprocess.Popen", lambda *a, **k: process)
    process.poll.return_value = 0
    process.returncode = 0
    assert start_target(root, state["active"], True, True) is None


def test_protection_backup_failure_blocks_transition_and_success_preserves_it(
    installed, monkeypatch
):
    store, root, source, state = installed
    manager = LaunchManagement(store.directory, root)
    target = {**state["active"], "slot": stage_release(source, root, SCHEMA_VERSION)}
    manager.transition = root, target, state
    with monkeypatch.context() as patch:
        patch.setattr(store, "backup", lambda: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            manager.finalize(store)
    assert current_state(root) == state and not (root / "pending.json").exists()
    assert manager.finalize(store) == root / "PJZStart.exe"
    protection = next((store.directory / "backups").glob("before-program-switch-*.pjzbackup"))
    inspect_backup(protection.read_bytes())
    assert current_state(root) == state


def test_prepare_update_and_rollback_use_same_ledger(installed, tmp_path, monkeypatch):
    store, root, _, state = installed
    manager = LaunchManagement(store.directory, root)
    source = release(tmp_path / "update", "0.17.0")
    package = archive_release(source, tmp_path / "update.zip")
    mock = MagicMock()
    monkeypatch.setattr("pjz.launch_management.subprocess.run", mock)
    version, _ = manager.prepare_update(package)
    assert version == "0.17.0"
    assert mock.call_args.args[0][-1] == "--self-test"
    assert manager.transition[1]["ledger_directory"] == str(store.directory)
    target = manager.transition[1]
    atomic_json(root / "current.json", {"format": 1, "active": target, "previous": state["active"]})
    assert manager.prepare_rollback() == "0.16.0"
    assert manager.transition[1]["ledger_directory"] == str(store.directory)


def test_first_install_is_explicit_and_does_not_move_ledger(installed, tmp_path, monkeypatch):
    store, _, source, _ = installed
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "SyntheticProfile"))
    monkeypatch.setattr("pjz.launch_management.sys.executable", str(source / "PJZSoftware.exe"))
    monkeypatch.setattr(LaunchManagement, "packaged", property(lambda self: True))
    manager = LaunchManagement(store.directory)
    root = manager.install_current()
    assert (root / "PJZStart.exe").read_bytes() == b"synthetic-starter"
    assert current_state(root)["active"]["ledger_directory"] == str(store.directory)
    assert store.path.exists() and not manager.info()["can_switch"]
    assert manager.install_current() == root


def test_runtime_and_restored_target_are_authenticated_and_opaque(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pjz.api import create_app

    store = LedgerStore(tmp_path / "ledger")
    root = tmp_path / "profile"
    manager = LaunchManagement(store.directory, root)
    monkeypatch.setattr(LaunchManagement, "packaged", property(lambda self: True))
    app = create_app(store, "http://127.0.0.1:8765", launch=manager)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            assert client.get("/api/v1/runtime").status_code == 401
            headers = authenticate(app, client)
            assert client.get("/api/v1/runtime").json()["version"] == __version__
            assert (
                client.post("/api/v1/runtime/manage", json={}, headers=headers).status_code == 200
            )
            assert manager.attention.is_set()
            assert (
                client.post(
                    "/api/v1/runtime/open-restored",
                    json={"directory": "C:/outside"},
                    headers=headers,
                ).status_code
                == 422
            )
            payload = store.backup()
            response = client.post(
                "/api/v1/restores/preview",
                files={"file": ("synthetic.pjzbackup", payload)},
                headers=headers,
            )
            result = client.post(
                "/api/v1/restores/commit",
                json={"preview_token": response.json()["preview_token"]},
                headers=headers,
            ).json()
            token = result["restore_token"]
            assert (
                client.post(
                    "/api/v1/runtime/open-restored", json={"restore_token": token}
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/runtime/open-restored", json={"restore_token": token}, headers=headers
                ).status_code
                == 200
            )
            assert manager.switches == [Path(result["directory"])]
            assert (
                client.post(
                    "/api/v1/runtime/open-restored", json={"restore_token": token}, headers=headers
                ).status_code
                == 400
            )
    finally:
        store.close()


@pytest.mark.parametrize("version", [None, "0.15.0", __version__])
def test_duplicate_launch_reopens_only_matching_version(installed, monkeypatch, version):
    from filelock import FileLock
    from pjz.launcher import main

    store, _, _, _ = installed
    if version:
        atomic_json(
            store.directory / "runtime.json",
            {
                "version": version,
                "pid": os.getpid(),
                "executable": str(Path(sys.executable).resolve()),
            },
        )
    monkeypatch.setattr(
        "sys.argv",
        ["PJZSoftware", "--data-dir", str(store.directory), "--headless", "--no-browser"],
    )
    with FileLock(store.directory / "instance.lock"):
        if version == __version__:
            main()
            assert (store.directory / "reopen.request").exists()
        else:
            with pytest.raises(SystemExit) as error:
                main()
            assert error.value.code == 3
            assert not (store.directory / "reopen.request").exists()


def test_managed_binary_manifest_mismatch_cannot_open_ledger(installed, monkeypatch):
    from pjz.launcher import main

    store, root, source, _ = installed
    manifest = json.loads((source / "release.json").read_text("utf-8"))
    manifest["version"] = "99.0.0"
    atomic_json(source / "release.json", manifest)
    monkeypatch.setattr("sys.executable", str(source / "PJZSoftware.exe"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "PJZSoftware",
            "--data-dir",
            str(store.directory),
            "--managed-root",
            str(root),
            "--headless",
        ],
    )
    called = MagicMock()
    monkeypatch.setattr("pjz.launcher.serve", called)
    with pytest.raises(SystemExit):
        main()
    called.assert_not_called()
    assert not (store.directory / "runtime.json").exists()


def test_timeout_terminates_only_owned_child(installed, monkeypatch):
    _, root, _, state = installed
    process = MagicMock()
    process.poll.return_value = None
    monkeypatch.setattr("pjz.installation.subprocess.Popen", lambda *a, **k: process)
    ticks = iter([0, 41])
    monkeypatch.setattr("pjz.installation.time.monotonic", lambda: next(ticks))
    with pytest.raises(InstallError, match="UPDATE_START_TIMEOUT"):
        start_target(root, state["active"], True, True)
    process.terminate.assert_called_once()


def test_expired_restore_token_is_rejected(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pjz.api import create_app

    store = LedgerStore(tmp_path / "ledger")
    manager = LaunchManagement(store.directory, tmp_path / "profile")
    monkeypatch.setattr(LaunchManagement, "packaged", property(lambda self: True))
    app = create_app(store, "http://127.0.0.1:8765", launch=manager)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            headers = authenticate(app, client)
            payload = store.backup()
            preview = client.post(
                "/api/v1/restores/preview",
                files={"file": ("synthetic.pjzbackup", payload)},
                headers=headers,
            ).json()
            result = client.post(
                "/api/v1/restores/commit",
                json={"preview_token": preview["preview_token"]},
                headers=headers,
            ).json()
            with monkeypatch.context() as patch:
                patch.setattr("pjz.api.time.monotonic", lambda: 999999999999)
                assert (
                    client.post(
                        "/api/v1/runtime/open-restored",
                        json={"restore_token": result["restore_token"]},
                        headers=headers,
                    ).status_code
                    == 400
                )
            assert manager.switches == []
    finally:
        store.close()


def test_stale_runtime_metadata_never_reopens_old_instance():
    from pjz.installation import matching_instance

    executable = Path(sys.executable).resolve()
    assert matching_instance(
        {"version": __version__, "pid": os.getpid(), "executable": str(executable)},
        __version__,
        executable,
    )
    assert not matching_instance(
        {"version": __version__, "pid": 999999999, "executable": str(executable)},
        __version__,
        executable,
    )
    assert not matching_instance(
        {"version": __version__, "pid": os.getpid()}, __version__, executable
    )


def test_managed_runtime_metadata_records_program_image(installed, monkeypatch):
    from pjz.launcher import main

    store, root, source, _ = installed
    monkeypatch.setattr("sys.executable", str(source / "PJZSoftware.exe"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "PJZSoftware",
            "--data-dir",
            str(store.directory),
            "--managed-root",
            str(root),
            "--headless",
        ],
    )
    observed = []

    def serve(*args):
        observed.append(json.loads((root / "runtime.json").read_text("utf-8")))

    monkeypatch.setattr("pjz.launcher.serve", serve)
    main()
    assert observed[0]["executable"] == str((source / "PJZSoftware.exe").resolve())
    assert observed[0]["ledger_directory"] == str(store.directory)
    assert not (root / "runtime.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 alias regression")
def test_windows_short_profile_alias_is_canonicalized(installed):
    import ctypes
    from ctypes import wintypes

    store, root, _, state = installed
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetShortPathNameW.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetShortPathNameW(str(root), buffer, len(buffer))
    assert 0 < length < len(buffer)
    alias = Path(buffer.value)
    if alias == root:
        pytest.skip("Volume does not create distinct 8.3 aliases")
    manager = LaunchManagement(store.directory, alias)
    assert manager.root == root.resolve()
    manager.prepare_switch(store.directory)
    assert manager.transition[2] == state
    assert current_state(manager.root) == state
