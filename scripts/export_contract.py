"""Generate deterministic API contract without reading a user ledger."""

import json
import sys
import tempfile
from pathlib import Path

from pjz.api import create_app
from pjz.storage import LedgerStore

with tempfile.TemporaryDirectory() as temporary:
    store = LedgerStore(Path(temporary))
    schema = create_app(store, "http://127.0.0.1:8765").openapi()
    rendered = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target = Path("contracts/openapi.json")
    if "--check" in sys.argv:
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            raise SystemExit("OpenAPI contract out of date")
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    store.close()
