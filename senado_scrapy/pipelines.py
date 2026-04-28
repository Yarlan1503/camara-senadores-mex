"""Scrapy pipelines for SQLite storage with deduplication."""

from __future__ import annotations

from senado_scrapy.db import get_connection, init_db
from senado_scrapy.items import SenadorItem, VotacionItem, VotoNominalItem


class SenadoSQLitePipeline:
    """Pipeline to store scraped items into SQLite with upserts."""

    def __init__(self) -> None:
        self.conn: object = None  # sqlite3.Connection
        self._buffer_count: int = 0
        self._batch_size: int = 100

    def open_spider(self, spider: object) -> None:
        """Initialize DB connection and schema when spider opens."""
        init_db()
        self.conn = get_connection()

    def _flush_buffer(self) -> None:
        """Commit pending buffered writes and reset counter."""
        self.conn.commit()
        self._buffer_count = 0

    def close_spider(self, spider: object) -> None:
        """Flush remaining buffer and close DB connection."""
        if self.conn:
            if self._buffer_count > 0:
                self._flush_buffer()
            self.conn.close()

    def process_item(self, item: object, spider: object) -> object:
        """Route item to appropriate handler based on type."""
        if isinstance(item, VotacionItem):
            self._upsert_votacion(item)
        elif isinstance(item, VotoNominalItem):
            self._insert_voto_nominal(item)
        elif isinstance(item, SenadorItem):
            self._upsert_senador(item)
        return item

    def _upsert_votacion(self, item: VotacionItem) -> None:
        """INSERT OR REPLACE a votación."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO votaciones (id, legislature, year, period, date, url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["legislature"],
                item["year"],
                item["period"],
                item["date"],
                item["url"],
            ),
        )
        self._buffer_count += 1
        if self._buffer_count >= self._batch_size:
            self._flush_buffer()

    def _insert_voto_nominal(self, item: VotoNominalItem) -> None:
        """INSERT OR IGNORE a voto nominal (dedup by UNIQUE constraint)."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO votos_nominales (votacion_id, senador_id, nombre, partido, voto)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item["votacion_id"],
                item["senador_id"],
                item["nombre"],
                item["partido"],
                item["voto"],
            ),
        )
        self._buffer_count += 1
        if self._buffer_count >= self._batch_size:
            self._flush_buffer()

    def _upsert_senador(self, item: SenadorItem) -> None:
        """INSERT OR REPLACE a senador."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO senadores (id, nombre, sexo, tipo_eleccion, estado, url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["nombre"],
                item.get("sexo"),
                item.get("tipo_eleccion"),
                item.get("estado"),
                item["url"],
            ),
        )
        self._buffer_count += 1
        if self._buffer_count >= self._batch_size:
            self._flush_buffer()
