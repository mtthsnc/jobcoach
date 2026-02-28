#!/usr/bin/env python3
from __future__ import annotations

import os
from wsgiref.simple_server import make_server

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
