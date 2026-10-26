"""Windows launcher with visible lifecycle; also usable headlessly for smoke checks."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from pjz.api import create_app
from pjz.storage import LedgerStore


def asset_directory() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


def main() -> None:
    parser = argparse.ArgumentParser(description="PJZSoftware 本地启动器")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--headless", action="store_true")
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
    directory.mkdir(parents=True, exist_ok=True)
    lock = FileLock(directory / "instance.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        (directory / "reopen.request").touch()
        return
    try:
        serve(directory, args.headless, args.no_browser)
    finally:
        lock.release()


def serve(directory: Path, headless: bool, no_browser: bool) -> None:
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

    app = create_app(store, origin, assets, shutdown=stop)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            log_level="critical",
            host="127.0.0.1",
            port=port,
            ws="none",
            lifespan="off",
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

    def open_page() -> None:
        token = app.state.session.issue_bootstrap()
        webbrowser.open(origin + "/#bootstrap=" + token)

    request_file = directory / "reopen.request"
    if not no_browser:
        open_page()
    try:
        if headless:
            while worker.is_alive():
                if request_file.exists():
                    request_file.unlink(missing_ok=True)
                    if not no_browser:
                        open_page()
                time.sleep(0.1)
        else:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.title("PJZSoftware · 本地服务")
            root.geometry("440x240")
            root.resizable(False, False)
            ttk.Label(root, text="PJZSoftware", font=("Microsoft YaHei UI", 18)).pack(pady=15)
            ttk.Label(root, text="服务仅运行在本机。关闭浏览器不会退出软件。").pack(pady=5)
            ttk.Button(root, text="打开软件", command=open_page).pack(pady=8)
            ttk.Button(root, text="退出软件", command=stop).pack(pady=8)
            root.protocol("WM_DELETE_WINDOW", stop)

            def poll() -> None:
                if not worker.is_alive():
                    root.destroy()
                    return
                if request_file.exists():
                    request_file.unlink(missing_ok=True)
                    open_page()
                    root.lift()
                root.after(200, poll)

            poll()
            root.mainloop()
    except KeyboardInterrupt:
        stop()
    finally:
        stop()
        worker.join(timeout=15)
        if worker.is_alive():
            raise SystemExit("服务仍在退出，请勿删除账本目录。")
        store.close()
        sock.close()
        request_file.unlink(missing_ok=True)
