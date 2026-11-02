"""Small, stable per-user entry point, kept outside replaceable version directories."""

import argparse
import sys
from pathlib import Path

from pjz.installation import dispatch

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--no-browser", action="store_true")
args = parser.parse_args()
try:
    error = dispatch(Path(sys.executable).resolve().parent, args.headless, args.no_browser)
    if error and not args.headless:
        from tkinter import messagebox

        messagebox.showwarning(
            "PJZSoftware",
            "新版本未能完成启动，已尝试回到原版。请先退出其他旧实例，再重新选择更新包。",
        )
except Exception:
    if not args.headless:
        from tkinter import messagebox

        messagebox.showerror(
            "PJZSoftware",
            "固定入口暂时无法启动，请先退出其他实例，或使用保留的原版便携目录。账本未被删除。",
        )
    raise SystemExit(1) from None
