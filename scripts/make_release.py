"""Write an exact local release manifest after both Windows executables are built."""

import argparse
import hashlib
from pathlib import Path

from pjz import __version__
from pjz.installation import atomic_json, verify_release
from pjz.storage import SCHEMA_VERSION

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
args = parser.parse_args()
root = args.directory.resolve()
files = {}
for path in sorted(root.rglob("*")):
    if path.is_file() and path != root / "release.json":
        with path.open("rb") as stream:
            files[path.relative_to(root).as_posix()] = {
                "size": path.stat().st_size,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
            }
atomic_json(
    root / "release.json",
    {
        "format": 1,
        "protocol": 1,
        "version": __version__,
        "schema": SCHEMA_VERSION,
        "files": files,
    },
)
verify_release(root)
print("PASS: exact release manifest")
