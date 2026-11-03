"""Native-only installation actions. HTTP can request attention, never choose executables."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from filelock import FileLock

from pjz import __version__
from pjz.installation import (
    InstallError,
    atomic_json,
    current_state,
    extract_release,
    queue_transition,
    stage_release,
    target_path,
    verify_release,
)
from pjz.storage import SCHEMA_VERSION, LedgerStore, write_verified_backup


class LaunchManagement:
    def __init__(self, directory: Path, root: Path | None = None, interactive: bool = True) -> None:
        self.managed_session = root is not None
        self.interactive = interactive
        self.directory = directory.resolve()
        self.root = root.resolve() if root else None
        self.attention = threading.Event()
        self.switches: list[Path] = []
        self.transition: tuple[Path, dict[str, Any], dict[str, Any]] | None = None

    @property
    def packaged(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    def info(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "executable": str(Path(sys.executable).resolve()),
            "entry": str(self.root / "PJZStart.exe") if self.root else None,
            "can_manage": self.packaged and self.interactive,
            "can_switch": self.packaged and self.managed_session and self.interactive,
        }

    def request_switch(self, directory: Path) -> None:
        if not self.packaged or self.root is None:
            raise InstallError("MANAGED_ENTRY_REQUIRED")
        self.switches.append(directory)
        self.attention.set()

    def install_current(self) -> Path:
        if not self.packaged:
            raise InstallError("PACKAGED_ONLY")
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PJZSoftware" / "application"
        root = root.resolve()
        if (root / "current.json").exists():
            old = current_state(root)
            if verify_release(target_path(root, old["active"]))["schema"] != SCHEMA_VERSION:
                # Keep the old schema installation intact; a fresh starter must not
                # dispatch a migrated ledger to the old executable.
                root = root.with_name("application-schema-" + str(SCHEMA_VERSION))
        root.mkdir(parents=True, exist_ok=True)
        with FileLock(root / "manager.lock", timeout=0):
            if (root / "current.json").exists():
                state = current_state(root)
                if Path(state["active"]["ledger_directory"]).resolve() != self.directory:
                    raise InstallError("MANAGED_LEDGER_MISMATCH")
                self.root = root
                return root
            source = Path(sys.executable).resolve().parent
            slot = stage_release(source, root, SCHEMA_VERSION)
            temporary = root / (".starter-" + uuid.uuid4().hex)
            try:
                shutil.copyfile(source / "PJZStart.exe", temporary)
                os.replace(temporary, root / "PJZStart.exe")
            finally:
                temporary.unlink(missing_ok=True)
            atomic_json(
                root / "current.json",
                {
                    "format": 1,
                    "active": {"slot": slot, "ledger_directory": str(self.directory)},
                    "previous": None,
                },
            )
        self.root = root
        return root

    def prepare_update(self, package: Path) -> tuple[str, str]:
        if self.root is None:
            raise InstallError("MANAGED_ENTRY_REQUIRED")
        with tempfile.TemporaryDirectory(prefix="pjz-release-") as temporary:
            source = extract_release(package, Path(temporary))
            root = self.root
            manifest = verify_release(source)
            if manifest["schema"] != SCHEMA_VERSION:
                raise InstallError("UPDATE_SCHEMA_MISMATCH")
            # Only the explicitly selected native package is executed, on synthetic data.
            subprocess.run(
                [str(source / "PJZSoftware.exe"), "--self-test"],
                check=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with FileLock(root / "manager.lock", timeout=0):
                state = current_state(root)
                slot = stage_release(source, root, SCHEMA_VERSION)
            target = {"slot": slot, "ledger_directory": str(self.directory)}
            self.transition = root, target, state
            return str(manifest["version"]), str(root / "versions" / slot)

    def prepare_rollback(self) -> str:
        if self.root is None:
            raise InstallError("MANAGED_ENTRY_REQUIRED")
        state = current_state(self.root)
        previous = state.get("previous")
        if previous is None:
            raise InstallError("NO_PREVIOUS_VERSION")
        manifest = verify_release(target_path(self.root, previous))
        if manifest["schema"] != SCHEMA_VERSION:
            raise InstallError("UPDATE_SCHEMA_MISMATCH")
        target = {"slot": previous["slot"], "ledger_directory": str(self.directory)}
        self.transition = self.root, target, state
        return str(manifest["version"])

    def prepare_switch(self, directory: Path) -> None:
        if self.root is None:
            raise InstallError("MANAGED_ENTRY_REQUIRED")
        state = current_state(self.root)
        self.transition = self.root, {**state["active"], "ledger_directory": str(directory)}, state

    def finalize(self, store: LedgerStore) -> Path | None:
        """Called only after HTTP stops and in-flight writes finish, before closing the store."""
        if self.transition is None:
            return None
        root, target, state = self.transition
        with FileLock(root / "manager.lock", timeout=0):
            if current_state(root) != state:
                raise InstallError("INSTALLATION_CHANGED")
            backup = (
                store.directory
                / "backups"
                / ("before-program-switch-" + uuid.uuid4().hex + ".pjzbackup")
            )
            backup.parent.mkdir(exist_ok=True)
            write_verified_backup(backup, store.backup())
            queue_transition(root, target, state)
        return root / "PJZStart.exe"

    def desktop_shortcut(self) -> None:
        if self.root is None or os.name != "nt":
            raise InstallError("MANAGED_ENTRY_REQUIRED")
        # Values go through environment variables, never interpolated into shell source.
        script = (
            "$ErrorActionPreference='Stop'; $w=New-Object -ComObject WScript.Shell; "
            "$p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'PJZ记账.lnk'; "
            "$s=$w.CreateShortcut($p); $s.TargetPath=$env:PJZ_ENTRY_TARGET; "
            "$s.WorkingDirectory=$env:PJZ_ENTRY_ROOT; $s.Save()"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={
                **os.environ,
                "PJZ_ENTRY_TARGET": str(self.root / "PJZStart.exe"),
                "PJZ_ENTRY_ROOT": str(self.root),
            },
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        )

    def manage(self, window: Any, stop: Any) -> None:
        from tkinter import filedialog, messagebox

        if self.root is None:
            if messagebox.askyesno(
                "设置固定入口",
                "将当前完整程序保存到当前 Windows 用户目录，账本留在原位置。是否设置固定启动入口？",
                parent=window,
            ):
                installed = self.install_current()
                if messagebox.askyesno(
                    "固定入口已保存", "是否创建桌面“PJZ记账”快捷方式？", parent=window
                ):
                    self.desktop_shortcut()
                selected_version = verify_release(
                    target_path(installed, current_state(installed)["active"])
                )["version"]
                messagebox.showinfo(
                    "固定入口已保存",
                    f"固定入口目前指向 v{selected_version}：\n{installed / 'PJZStart.exe'}\n"
                    "请先退出当前便携版；以后从固定入口选择本地 ZIP 更新。",
                    parent=window,
                )
            return
        dialog = __import__("tkinter").Toplevel(window)
        dialog.title("启动与更新管理")
        from tkinter import ttk

        ttk.Label(
            dialog,
            text=f"当前运行 v{__version__}\n固定入口：{self.root / 'PJZStart.exe'}",
            wraplength=560,
        ).pack(padx=20, pady=15)

        def update() -> None:
            package = filedialog.askopenfilename(
                parent=dialog,
                title="选择可信来源的本地程序 ZIP",
                filetypes=[("PJZ 程序包", "*.zip")],
            )
            if not package:
                return
            try:
                version, location = self.prepare_update(Path(package))
                if messagebox.askyesno(
                    "确认更新",
                    f"当前 v{__version__} → v{version}\n新版本位置：{location}\n"
                    "即将退出并备份当前账本。旧版保留，启动失败尝试回到原版。继续？",
                    parent=dialog,
                ):
                    dialog.destroy()
                    stop()
                else:
                    self.transition = None
            except Exception:
                self.transition = None
                messagebox.showerror(
                    "更新未开始",
                    "包校验、自检或保存失败。请选择完整且 schema 兼容的新版程序包，"
                    "并检查目录权限／空间；当前账本未改变。",
                    parent=dialog,
                )

        def rollback() -> None:
            try:
                version = self.prepare_rollback()
                if messagebox.askyesno(
                    "回退程序", f"回到 v{version}？将先备份，账本数据不回退。", parent=dialog
                ):
                    dialog.destroy()
                    stop()
                else:
                    self.transition = None
            except Exception:
                self.transition = None
                messagebox.showerror(
                    "暂不能回退", "没有可用且兼容的上一版本。当前账本未改变。", parent=dialog
                )

        ttk.Button(dialog, text="选择本地 ZIP 更新", command=update).pack(pady=6)
        ttk.Button(dialog, text="回退上一程序版本", command=rollback).pack(pady=6)

        def shortcut() -> None:
            try:
                self.desktop_shortcut()
                messagebox.showinfo("快捷方式已保存", "以后双击桌面“PJZ记账”打开。", parent=dialog)
            except Exception:
                messagebox.showerror(
                    "快捷方式未保存", "可直接使用上方固定入口；请检查桌面目录权限。", parent=dialog
                )

        ttk.Button(dialog, text="创建／修复桌面快捷方式", command=shortcut).pack(padx=20, pady=12)
