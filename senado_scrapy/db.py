"""SQLite database helper with schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "senado.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS votaciones (
    id INTEGER PRIMARY KEY,
    legislature INTEGER NOT NULL,
    year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    date TEXT NOT NULL,
    url TEXT NOT NULL,
    scraped_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS votos_nominales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    votacion_id INTEGER NOT NULL REFERENCES votaciones(id),
    senador_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    partido TEXT NOT NULL,
    voto TEXT NOT NULL,
    UNIQUE(votacion_id, senador_id)
);

CREATE TABLE IF NOT EXISTS senadores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    sexo TEXT,
    tipo_eleccion TEXT,
    estado TEXT,
    url TEXT NOT NULL,
    scraped_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_votos_votacion_id ON votos_nominales(votacion_id);
CREATE INDEX IF NOT EXISTS idx_votos_senador_id ON votos_nominales(senador_id);
"""


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with proper configuration."""
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database with schema."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
