"""Isolated browser test server; fixed credential only exists in synthetic tests."""

import tempfile
from pathlib import Path

import uvicorn
from pjz.api import create_app
from pjz.launcher import asset_directory
from pjz.storage import LedgerStore

with tempfile.TemporaryDirectory(prefix="pjz-browser-") as temporary:
    store = LedgerStore(Path(temporary))
    app = create_app(store, "http://127.0.0.1:8765", asset_directory())
    app.state.session.bootstrap = "synthetic-browser-bootstrap"
    try:
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False, log_level="critical")
    finally:
        store.close()
