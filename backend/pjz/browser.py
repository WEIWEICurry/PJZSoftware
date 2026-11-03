"""Open local ledger URLs without invoking the Windows app-choice dialog."""

from __future__ import annotations

import ctypes
import os
import subprocess
import webbrowser
from collections.abc import Iterator
from itertools import chain
from pathlib import Path


def association_executable(protocol: str) -> Path | None:
    """Read the effective system association; never write default-app settings."""
    from ctypes import wintypes

    try:
        query = ctypes.WinDLL("Shlwapi.dll").AssocQueryStringW
        query.argtypes = [
            wintypes.DWORD,
            ctypes.c_int,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query.restype = ctypes.c_long
        size = wintypes.DWORD(32768)
        output = ctypes.create_unicode_buffer(size.value)
        if query(0, 2, protocol, None, output, ctypes.byref(size)) == 0 and output.value:
            return Path(output.value)
    except (OSError, AttributeError):
        pass
    return None


def fallback_executables() -> Iterator[Path]:
    import winreg

    for name in ("msedge.exe", "chrome.exe", "firefox.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    key_path = (
                        "Software/Microsoft/Windows/CurrentVersion/App Paths".replace("/", chr(92))
                        + chr(92)
                        + name
                    )
                    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                        value, kind = winreg.QueryValueEx(key, "")
                        if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                            yield Path(os.path.expandvars(str(value).strip('"')))
                except OSError:
                    continue
    for base in (
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if base:
            for suffix in (
                "Microsoft/Edge/Application/msedge.exe",
                "Google/Chrome/Application/chrome.exe",
                "Mozilla Firefox/firefox.exe",
            ):
                yield Path(base) / suffix


def open_windows(url: str) -> bool:
    candidates = [association_executable("http"), association_executable("https")]
    seen: set[str] = set()
    for path in chain(candidates, fallback_executables()):
        if path is None:
            continue
        name = path.name.lower()
        if name in (
            "openwith.exe",
            "rundll32.exe",
            "explorer.exe",
            "applicationframehost.exe",
            "launchwinapp.exe",
        ):
            continue
        identity = os.path.normcase(str(path))
        if (
            identity in seen
            or path.suffix.lower() != ".exe"
            or not path.is_absolute()
            or not path.is_file()
        ):
            continue
        seen.add(identity)
        try:
            subprocess.Popen(
                [str(path), url],
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except OSError:
            continue
    return False


def open_browser(url: str) -> bool:
    if os.name == "nt":
        return open_windows(url)
    return webbrowser.open(url)
