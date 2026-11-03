"""Windows launcher with visible lifecycle; also usable headlessly for smoke checks."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from pjz import __version__
from pjz.api import create_app
from pjz.browser import open_browser
from pjz.installation import atomic_json, matching_instance, read_json, verify_release
from pjz.launch_management import LaunchManagement
from pjz.storage import SCHEMA_VERSION, LedgerStore


def asset_directory() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


def main() -> None:
    parser = argparse.ArgumentParser(description="PJZSoftware 本地启动器")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--managed-root", type=Path)
    parser.add_argument("--ready-id")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--show-service", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        from pjz.selftest import run

        run()
        return
    directory = args.data_dir or (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PJZSoftware" / "ledgers" / "default"
    )
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = args.managed_root.resolve() if args.managed_root else None
    if args.ready_id and (not root or not re.fullmatch(r"[a-f0-9]{32}", args.ready_id)):
        raise SystemExit("无效启动握手。")
    if root:
        manifest = verify_release(Path(sys.executable).resolve().parent)
        if manifest["version"] != __version__ or manifest["schema"] != SCHEMA_VERSION:
            raise SystemExit(3)
    management = LaunchManagement(directory, root, interactive=not args.headless)
    lock = FileLock(directory / "instance.lock")
    profile_lock = FileLock(root / "runtime.lock") if root else None
    try:
        if profile_lock:
            profile_lock.acquire(timeout=0)
        lock.acquire(timeout=0)
    except Timeout:
        if profile_lock and profile_lock.is_locked:
            profile_lock.release()
        try:
            running = read_json((root / "runtime.json") if root else directory / "runtime.json")
            if root and running.get("ledger_directory") != str(directory):
                running = {}
        except (OSError, ValueError):
            running = {}
        if matching_instance(running, __version__, Path(sys.executable)):
            (directory / "reopen.request").touch()
            return
        if not args.headless:
            from tkinter import messagebox

            messagebox.showwarning(
                "请先退出旧版",
                "检测到账本或固定入口仍被其他版本占用。请在原程序点击“退出软件”，再重新打开；软件不会强制结束旧程序。",
            )
        raise SystemExit(3) from None
    restart = None
    try:
        atomic_json(
            directory / "runtime.json",
            {
                "version": __version__,
                "pid": os.getpid(),
                "executable": str(Path(sys.executable).resolve()),
            },
        )
        if root:
            atomic_json(
                root / "runtime.json",
                {
                    "version": __version__,
                    "pid": os.getpid(),
                    "ledger_directory": str(directory),
                    "executable": str(Path(sys.executable).resolve()),
                },
            )
        restart = serve(
            directory, args.headless, args.no_browser, management, args.ready_id, args.show_service
        )
    finally:
        (directory / "runtime.json").unlink(missing_ok=True)
        if root:
            (root / "runtime.json").unlink(missing_ok=True)
        lock.release()
        if profile_lock:
            profile_lock.release()
    if restart:
        subprocess.Popen(
            [str(restart)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )


def serve(
    directory: Path,
    headless: bool,
    no_browser: bool,
    management: LaunchManagement | None = None,
    ready_id: str | None = None,
    show_service: bool = False,
) -> Path | None:
    management = management or LaunchManagement(directory, interactive=not headless)
    assets = asset_directory()
    if not (assets / "index.html").is_file():
        raise SystemExit("界面尚未构建，请先执行 frontend 的 npm run build。")
    store = LedgerStore(directory)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"

    def stop() -> None:
        server.should_exit = True

    app = create_app(store, origin, assets, shutdown=stop, launch=management)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            log_level="critical",
            host="127.0.0.1",
            port=port,
            ws="none",
            lifespan="on",
        )
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not worker.is_alive() or time.monotonic() > deadline:
            stop()
            store.close()
            sock.close()
            raise SystemExit("本地服务启动失败。请检查目录权限与端口。")
        time.sleep(0.05)

    if ready_id and management.root:
        atomic_json(
            management.root / "ready" / (ready_id + ".json"),
            {"pid": os.getpid(), "version": __version__, "id": ready_id},
        )

    def open_page() -> bool:
        token = app.state.session.issue_bootstrap()
        return open_browser(origin + "/#bootstrap=" + token)

    request_file = directory / "reopen.request"
    if not no_browser:
        show_service = not open_page() or show_service
    try:
        if headless:
            while worker.is_alive():
                if request_file.exists():
                    request_file.unlink(missing_ok=True)
                    if not no_browser:
                        open_page()
                time.sleep(0.1)
        else:
            run_service_window(
                management, worker, request_file, open_page, stop, show_service, no_browser
            )
    except KeyboardInterrupt:
        stop()
    finally:
        stop()
        worker.join(timeout=60)
        if worker.is_alive():
            raise SystemExit("服务仍在退出，请勿删除账本目录。")
        try:
            restart = management.finalize(store)
        except Exception:
            restart = management.root / "PJZStart.exe" if management.root else None
            if not headless:
                from tkinter import messagebox

                messagebox.showerror(
                    "切换未完成",
                    "保护备份或候选配置保存失败，未切换版本／账本，将尝试重新打开原版。",
                )
        finally:
            store.close()
            sock.close()
            request_file.unlink(missing_ok=True)
    return restart


def run_service_window(
    management: LaunchManagement,
    worker: threading.Thread,
    request_file: Path,
    open_page: Callable[[], bool],
    stop: Callable[[], None],
    show_service: bool = False,
    no_browser: bool = False,
) -> None:
    """Keep the event loop available while normal launches show only the ledger."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.withdraw()
    root.title(f"PJZSoftware v{__version__} · 本地服务")
    root.geometry("620x360")
    root.resizable(False, False)
    ttk.Label(root, text="PJZSoftware", font=("Microsoft YaHei UI", 18)).pack(pady=15)
    ttk.Label(
        root,
        text="服务仅运行在本机，关闭浏览器或管理窗口不会退出软件。\n请用页面或下方的“退出软件”按钮结束运行。",
    ).pack(pady=5)
    ttk.Label(
        root,
        text=f"当前版本：v{__version__}\n程序：{Path(sys.executable).resolve()}",
        wraplength=580,
    ).pack(pady=8)
    ttk.Button(root, text="打开软件", command=open_page).pack(pady=8)

    def reveal() -> None:
        root.deiconify()
        root.lift()
        root.focus_set()

    def manage() -> None:
        reveal()
        try:
            management.manage(root, stop)
        except Exception:
            from tkinter import messagebox

            messagebox.showerror(
                "设置未完成",
                "固定入口保存失败，请检查磁盘空间和权限。原程序与账本仍保留。",
                parent=root,
            )

    ttk.Button(root, text="启动与更新管理", command=manage).pack(pady=8)
    ttk.Button(root, text="退出软件", command=stop).pack(pady=8)
    root.protocol("WM_DELETE_WINDOW", root.withdraw)

    def poll() -> None:
        if not worker.is_alive():
            root.destroy()
            return
        if request_file.exists():
            request_file.unlink(missing_ok=True)
            if not no_browser and not open_page():
                reveal()
        if management.attention.is_set():
            management.attention.clear()
            if management.switches:
                was_hidden = root.state() == "withdrawn"
                reveal()
                from tkinter import messagebox

                destination = management.switches.pop(0)
                if messagebox.askyesno(
                    "打开恢复副本",
                    "将先退出并备份当前账本，再打开刚验证的恢复副本。继续？",
                    parent=root,
                ):
                    management.prepare_switch(destination)
                    stop()
                elif was_hidden:
                    root.withdraw()
            else:
                manage()
        root.after(200, poll)

    if show_service:
        reveal()
    poll()
    root.mainloop()
