"""Service-window interaction regressions without touching the user's desktop."""

from unittest.mock import MagicMock

import pytest
from pjz.launch_management import LaunchManagement
from pjz.launcher import run_service_window


@pytest.fixture
def window(tmp_path, monkeypatch):
    root = MagicMock()
    state = {"visible": True, "destroyed": False}
    timers = []
    protocols = {}
    buttons = {}
    root.withdraw.side_effect = lambda: state.update(visible=False)
    root.deiconify.side_effect = lambda: state.update(visible=True)
    root.state.side_effect = lambda: "normal" if state["visible"] else "withdrawn"
    root.destroy.side_effect = lambda: state.update(destroyed=True)
    root.after.side_effect = lambda interval, callback: timers.append(callback)
    root.protocol.side_effect = lambda name, callback: protocols.update({name: callback})
    monkeypatch.setattr("tkinter.Tk", lambda: root)
    monkeypatch.setattr("tkinter.ttk.Label", MagicMock())

    def button(*args, **kwargs):
        buttons[kwargs["text"]] = kwargs["command"]
        return MagicMock()

    monkeypatch.setattr("tkinter.ttk.Button", button)
    manager = LaunchManagement(tmp_path)
    manager.manage = MagicMock()
    manager.prepare_switch = MagicMock()
    worker = MagicMock()
    worker.is_alive.return_value = True
    stop = MagicMock(side_effect=lambda: setattr(worker.is_alive, "return_value", False))
    return (
        root,
        state,
        timers,
        protocols,
        buttons,
        manager,
        worker,
        stop,
        tmp_path / "reopen.request",
    )


@pytest.mark.parametrize("show_service", [False, True])
def test_startup_visibility_and_explicit_exit(window, show_service):
    root, state, timers, _, buttons, manager, worker, stop, path = window

    def interact():
        assert state["visible"] is show_service
        assert worker.is_alive()
        buttons["退出软件"]()
        timers.pop(0)()
        assert state["destroyed"]

    root.mainloop.side_effect = interact
    run_service_window(manager, worker, path, MagicMock(return_value=True), stop, show_service)
    stop.assert_called_once()


@pytest.mark.parametrize("browser_opened", [True, False])
def test_duplicate_opens_browser_without_raising_window_unless_browser_failed(
    window, browser_opened
):
    root, state, timers, _, _, manager, worker, stop, path = window
    browser = MagicMock(return_value=browser_opened)

    def interact():
        assert not state["visible"]
        path.touch()
        timers.pop(0)()
        browser.assert_called_once()
        assert not path.exists()
        assert state["visible"] is (not browser_opened)
        stop.assert_not_called()
        stop()
        timers.pop(0)()
        assert state["destroyed"]

    root.mainloop.side_effect = interact
    run_service_window(manager, worker, path, browser, stop)


def test_management_can_be_revealed_closed_and_reopened_without_stopping(window):
    root, state, timers, protocols, _, manager, worker, stop, path = window

    def interact():
        assert not state["visible"]
        manager.attention.set()
        timers.pop(0)()
        assert state["visible"]
        manager.manage.assert_called_once_with(root, stop)
        protocols["WM_DELETE_WINDOW"]()
        assert not state["visible"] and worker.is_alive()
        stop.assert_not_called()
        manager.attention.set()
        timers.pop(0)()
        assert state["visible"] and manager.manage.call_count == 2
        stop()
        timers.pop(0)()
        assert state["destroyed"]

    root.mainloop.side_effect = interact
    run_service_window(manager, worker, path, MagicMock(return_value=True), stop)


@pytest.mark.parametrize("confirm", [False, True])
def test_restored_copy_confirmation_is_available_from_hidden_window(window, monkeypatch, confirm):
    root, state, timers, _, _, manager, worker, stop, path = window
    destination = path.parent / "synthetic-restored"

    def ask(*args, **kwargs):
        assert state["visible"]
        return confirm

    monkeypatch.setattr("tkinter.messagebox.askyesno", ask)

    def interact():
        assert not state["visible"]
        manager.switches.append(destination)
        manager.attention.set()
        timers.pop(0)()
        if confirm:
            manager.prepare_switch.assert_called_once_with(destination)
            stop.assert_called_once()
        else:
            assert not state["visible"] and worker.is_alive()
            manager.prepare_switch.assert_not_called()
            stop.assert_not_called()
            stop()
        timers.pop(0)()
        assert state["destroyed"]

    root.mainloop.side_effect = interact
    run_service_window(manager, worker, path, MagicMock(return_value=True), stop)


def test_no_browser_duplicate_does_not_open_real_browser(window):
    root, state, timers, _, _, manager, worker, stop, path = window
    browser = MagicMock(return_value=True)

    def interact():
        path.touch()
        timers.pop(0)()
        browser.assert_not_called()
        assert not state["visible"]
        stop()
        timers.pop(0)()

    root.mainloop.side_effect = interact
    run_service_window(manager, worker, path, browser, stop, no_browser=True)
