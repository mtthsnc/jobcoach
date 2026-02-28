from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_row_factory(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection
