#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api_gateway.app import create_app


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    db_path = os.environ.get("JOBCOACH_DB_PATH")

    app = create_app(db_path=db_path)
    with make_server(host, port, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
