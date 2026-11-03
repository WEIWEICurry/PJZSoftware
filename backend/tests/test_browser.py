"""Synthetic associations only; never launch the user's browser or alter defaults."""

from unittest.mock import MagicMock

from pjz import browser


def setup_browser(tmp_path, monkeypatch, http="default.exe", https=None, fallbacks=()):
    files = {}
    for name in [http, https, *fallbacks]:
        if name:
            path = tmp_path / name
            path.write_bytes(b"synthetic browser")
            files[name] = path
    monkeypatch.setattr(
        browser,
        "association_executable",
        lambda scheme: files.get(http if scheme == "http" else https),
    )
    monkeypatch.setattr(
        browser, "fallback_executables", lambda: iter(files[name] for name in fallbacks)
    )
    launch = MagicMock()
    monkeypatch.setattr(browser.subprocess, "Popen", launch)
    return files, launch


def test_default_used_with_url_as_single_argument(tmp_path, monkeypatch):
    files, launch = setup_browser(tmp_path, monkeypatch, fallbacks=("msedge.exe",))
    url = "http://127.0.0.1:12345/#bootstrap=synthetic-only"
    assert browser.open_windows(url)
    assert launch.call_args.args[0] == [str(files["default.exe"]), url]
    assert launch.call_args.kwargs["shell"] is False
    launch.assert_called_once()


def test_app_chooser_is_skipped_for_https_default(tmp_path, monkeypatch):
    files, launch = setup_browser(tmp_path, monkeypatch, http="OpenWith.exe", https="chrome.exe")
    assert browser.open_windows("http://127.0.0.1:12345/")
    assert launch.call_args.args[0][0] == str(files["chrome.exe"])


def test_missing_default_uses_installed_fallback(tmp_path, monkeypatch):
    files, launch = setup_browser(tmp_path, monkeypatch, http=None, fallbacks=("msedge.exe",))
    assert browser.open_windows("http://127.0.0.1:12345/")
    assert launch.call_args.args[0][0] == str(files["msedge.exe"])


def test_launch_failure_tries_next_candidate(tmp_path, monkeypatch):
    files, launch = setup_browser(tmp_path, monkeypatch, https="firefox.exe")
    launch.side_effect = [OSError("Synthetic launch failure"), MagicMock()]
    assert browser.open_windows("http://127.0.0.1:12345/")
    assert launch.call_args.args[0][0] == str(files["firefox.exe"])


def test_no_valid_browser_returns_failure_without_shell(tmp_path, monkeypatch):
    _, launch = setup_browser(tmp_path, monkeypatch, http="rundll32.exe")
    assert not browser.open_windows("http://127.0.0.1:12345/")
    launch.assert_not_called()
