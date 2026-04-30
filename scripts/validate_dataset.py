#!/usr/bin/env python3
"""Validate the Senado SQLite dataset without mutating it.

The validator intentionally opens the target database with SQLite URI
``mode=ro`` and does not use ``senado_scrapy.db.get_connection`` because that
helper configures write-oriented PRAGMAs for crawling.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from senado_scrapy.db import resolve_db_path  # noqa: E402


# Dataset contract: votos_nominales counts nominal votes by senators (``Sen.``)
# stored in the local snapshot. It is not expected to match the raw AJAX row
# count when the official fragment also contains non-senator rows such as
# ``Dip.``; audited mixed-row cases include vote IDs 891, 3450 and 4890.
EXPECTED_COUNTS = {
    "votaciones": 4_993,
    "votos_nominales": 454_094,
    "senadores": 700,
    "distinct_senador_id_en_votos": 737,
    "ids_sin_perfil": 37,
    "votos_ligados_a_ids_sin_perfil": 29_879,
    "voto_vacio": 14,
    "partido_vacio": 88,
}

EXPECTED_VOTOS_BY_LEGISLATURE = {
    60: 61_924,
    61: 65_869,
    62: 82_856,
    63: 73_790,
    64: 64_099,
    65: 76_953,
    66: 28_603,
}

REQUIRED_COLUMNS = {
    "votaciones": {"id", "legislature", "year", "period", "date", "url", "scraped_at"},
    "votos_nominales": {"id", "votacion_id", "senador_id", "nombre", "partido", "voto"},
    "senadores": {"id", "nombre", "sexo", "tipo_eleccion", "estado", "url", "scraped_at"},
}


@dataclass
class CheckResult:
    level: str
    name: str
    detail: str


class Validator:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.results: list[CheckResult] = []
        self.tables: set[str] = set()
        self.columns: dict[str, set[str]] = {}

    def pass_(self, name: str, detail: str) -> None:
        self.results.append(CheckResult("PASS", name, detail))

    def warn(self, name: str, detail: str) -> None:
        self.results.append(CheckResult("WARN", name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(CheckResult("FAIL", name, detail))

    def scalar(self, sql: str, params: tuple[object, ...] = ()) -> object:
        return self.conn.execute(sql, params).fetchone()[0]

    def rows(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def run(self) -> list[CheckResult]:
        self.check_integrity()
        self.check_schema()

        if not self.has_required_schema():
            self.fail("dataset checks", "Se omiten checks de datos porque faltan tablas/columnas requeridas")
            return self.results

        self.check_expected_counts()
        self.check_distribution()
        self.check_duplicates()
        self.check_warnings()
        return self.results

    def check_integrity(self) -> None:
        try:
            result = str(self.scalar("PRAGMA integrity_check"))
        except sqlite3.DatabaseError as exc:
            self.fail("integrity_check", f"No se pudo ejecutar PRAGMA integrity_check: {exc}")
            return

        if result == "ok":
            self.pass_("integrity_check", "PRAGMA integrity_check == ok")
        else:
            self.fail("integrity_check", f"PRAGMA integrity_check devolvió {result!r}")

    def check_schema(self) -> None:
        self.tables = {
            str(row[0])
            for row in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not str(row[0]).startswith("sqlite_")
        }
        missing_tables = set(REQUIRED_COLUMNS) - self.tables
        if missing_tables:
            self.fail("schema tables", f"Faltan tablas requeridas: {sorted(missing_tables)}")
        else:
            self.pass_("schema tables", f"Tablas requeridas presentes: {sorted(REQUIRED_COLUMNS)}")

        for table in sorted(REQUIRED_COLUMNS):
            if table not in self.tables:
                continue
            cols = {str(row[1]) for row in self.rows(f"PRAGMA table_info({table})")}
            self.columns[table] = cols
            missing_cols = REQUIRED_COLUMNS[table] - cols
            if missing_cols:
                self.fail("schema columns", f"{table}: faltan columnas {sorted(missing_cols)}")
            else:
                self.pass_("schema columns", f"{table}: columnas requeridas presentes")

    def has_required_schema(self) -> bool:
        return all(table in self.tables and REQUIRED_COLUMNS[table] <= self.columns.get(table, set()) for table in REQUIRED_COLUMNS)

    def check_expected_counts(self) -> None:
        actuals = {
            "votaciones": self.scalar("SELECT COUNT(*) FROM votaciones"),
            "votos_nominales": self.scalar("SELECT COUNT(*) FROM votos_nominales"),
            "senadores": self.scalar("SELECT COUNT(*) FROM senadores"),
            "distinct_senador_id_en_votos": self.scalar("SELECT COUNT(DISTINCT senador_id) FROM votos_nominales"),
            "ids_sin_perfil": self.scalar(
                """
                SELECT COUNT(*)
                FROM (SELECT DISTINCT senador_id FROM votos_nominales)
                WHERE senador_id NOT IN (SELECT id FROM senadores)
                """
            ),
            "votos_ligados_a_ids_sin_perfil": self.scalar(
                """
                SELECT COUNT(*)
                FROM votos_nominales AS vn
                WHERE NOT EXISTS (SELECT 1 FROM senadores AS s WHERE s.id = vn.senador_id)
                """
            ),
            "voto_vacio": self.scalar("SELECT COUNT(*) FROM votos_nominales WHERE TRIM(COALESCE(voto, '')) = ''"),
            "partido_vacio": self.scalar("SELECT COUNT(*) FROM votos_nominales WHERE TRIM(COALESCE(partido, '')) = ''"),
        }

        for name, expected in EXPECTED_COUNTS.items():
            actual = int(actuals[name])
            if actual == expected:
                self.pass_(name, f"{actual:,} == esperado {expected:,}")
            else:
                self.fail(name, f"{actual:,} != esperado {expected:,}")

    def check_distribution(self) -> None:
        rows = self.rows(
            """
            SELECT v.legislature, COUNT(*) AS total
            FROM votos_nominales AS vn
            JOIN votaciones AS v ON v.id = vn.votacion_id
            GROUP BY v.legislature
            ORDER BY v.legislature
            """
        )
        actual = {int(row[0]): int(row[1]) for row in rows}
        if actual == EXPECTED_VOTOS_BY_LEGISLATURE:
            detail = ", ".join(f"{leg}={total:,}" for leg, total in actual.items())
            self.pass_("distribución por legislatura", detail)
        else:
            self.fail(
                "distribución por legislatura",
                f"actual={actual} esperado={EXPECTED_VOTOS_BY_LEGISLATURE}",
            )

    def check_duplicates(self) -> None:
        # Logical keys inferred from the declared schema in senado_scrapy/db.py:
        # - votaciones.id and senadores.id are primary keys.
        # - votos_nominales has UNIQUE(votacion_id, senador_id).
        duplicate_votes = int(
            self.scalar(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT votacion_id, senador_id
                    FROM votos_nominales
                    GROUP BY votacion_id, senador_id
                    HAVING COUNT(*) > 1
                )
                """
            )
        )
        if duplicate_votes == 0:
            self.pass_("duplicados votos_nominales", "0 duplicados por clave lógica (votacion_id, senador_id)")
        else:
            self.fail("duplicados votos_nominales", f"{duplicate_votes} claves duplicadas (votacion_id, senador_id)")

        for table in ("votaciones", "senadores"):
            duplicate_ids = int(
                self.scalar(
                    f"""
                    SELECT COUNT(*)
                    FROM (
                        SELECT id
                        FROM {table}
                        GROUP BY id
                        HAVING COUNT(*) > 1
                    )
                    """
                )
            )
            if duplicate_ids == 0:
                self.pass_(f"duplicados {table}", "0 duplicados por clave primaria id")
            else:
                self.fail(f"duplicados {table}", f"{duplicate_ids} IDs duplicados")

    def check_warnings(self) -> None:
        votaciones_sin_votos = [
            int(row[0])
            for row in self.rows(
                """
                SELECT v.id
                FROM votaciones AS v
                LEFT JOIN votos_nominales AS vn ON vn.votacion_id = v.id
                WHERE vn.id IS NULL
                ORDER BY v.id
                """
            )
        ]
        if votaciones_sin_votos:
            self.warn(
                "votaciones sin votos",
                f"{len(votaciones_sin_votos)} IDs: {format_id_list(votaciones_sin_votos)}",
            )
        else:
            self.pass_("votaciones sin votos", "0 votaciones sin votos nominales")

        missing_profile_ids = [
            int(row[0])
            for row in self.rows(
                """
                SELECT DISTINCT vn.senador_id
                FROM votos_nominales AS vn
                WHERE NOT EXISTS (SELECT 1 FROM senadores AS s WHERE s.id = vn.senador_id)
                ORDER BY vn.senador_id
                """
            )
        ]
        if missing_profile_ids:
            self.warn(
                "perfiles faltantes aceptados",
                f"{len(missing_profile_ids)} IDs sin perfil: {format_id_list(missing_profile_ids)}",
            )

        for table, fields in {"senadores": ["nombre", "url"], "votos_nominales": ["nombre", "partido", "voto"]}.items():
            for field in fields:
                empty_count = int(self.scalar(f"SELECT COUNT(*) FROM {table} WHERE TRIM(COALESCE({field}, '')) = ''"))
                if empty_count:
                    self.warn("campos vacíos aceptados", f"{table}.{field}: {empty_count:,} filas vacías")


def format_id_list(ids: list[int], limit: int = 30) -> str:
    shown = ", ".join(str(item) for item in ids[:limit])
    if len(ids) > limit:
        shown = f"{shown}, ..."
    return shown


def open_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"No existe la DB: {db_path}")
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate senado.db dataset contract in read-only mode.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path. Defaults to SENADO_DB_PATH or ./senado.db")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = resolve_db_path(args.db)

    print(f"Validando dataset Senado: {db_path}")
    print("Conexión SQLite: READ-ONLY (URI mode=ro)")
    print("Contrato votos_nominales: subconjunto nominal de senadores (Sen.), no AJAX bruto con filas Dip.")

    try:
        with open_readonly(db_path) as conn:
            results = Validator(conn).run()
    except (OSError, sqlite3.DatabaseError) as exc:
        print(f"FAIL open database: {exc}")
        return 2

    for result in results:
        print(f"{result.level} {result.name}: {result.detail}")

    failures = [result for result in results if result.level == "FAIL"]
    warnings = [result for result in results if result.level == "WARN"]
    print(f"Resumen: {len(results) - len(failures) - len(warnings)} PASS, {len(warnings)} WARN, {len(failures)} FAIL")

    if failures:
        print("Resultado: FAIL")
        return 1

    print("Resultado: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
