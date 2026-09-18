"""Enables `python -m fastdicomstructure`. Kept as a thin shim, separate
from cli.py, so cli.py stays freely importable (e.g. for in-process
qualification calling `cli.main(argv)` directly) without triggering any
`__main__`-only side effect -- a standard Python idiom (see e.g.
`http.server`, `json.tool`)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
