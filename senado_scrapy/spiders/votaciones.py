"""Spider para recorrer votaciones nominales del Senado mexicano.

Recorre IDs de https://www.senado.gob.mx/66/votacion/{ID},
extrayendo metadata temporal (legislatura, año, periodo, fecha)
y votos nominales individuales vía endpoint AJAX.

La decisión de si una votación tiene datos se toma en parse_votes()
según el resultado del endpoint AJAX, no por la presencia de #viewTable.

Uso:
    scrapy crawl votaciones
    scrapy crawl votaciones -a max_id=50
    scrapy crawl votaciones -a ids=347,891,2103,2789,3671,4256,4890

Si se pasa ``ids``, se usan esos IDs explícitos (comma-separated).
Si no, se itera range(1, max_id+1) como antes.
"""

import re

import scrapy
from scrapy.http import Response

from senado_scrapy.items import VotacionItem, VotoNominalItem

# ---------------------------------------------------------------------------
# Constantes de conversión
# ---------------------------------------------------------------------------

ROMAN_MAP: dict[str, int] = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

SPANISH_ORDINALS: dict[str, int] = {
    "primer": 1,
    "primero": 1,
    "primera": 1,
    "segundo": 2,
    "segunda": 2,
    "tercer": 3,
    "tercero": 3,
    "tercera": 3,
    "cuarto": 4,
    "cuarta": 4,
    "quinto": 5,
    "quinta": 5,
    "sexto": 6,
    "sexta": 6,
    "séptimo": 7,
    "septimo": 7,
    "séptima": 7,
    "septima": 7,
    "octavo": 8,
    "octava": 8,
    "noveno": 9,
    "novena": 9,
    "décimo": 10,
    "decimo": 10,
    "décima": 10,
    "decima": 10,
}

SPANISH_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

LEGISLATURE_DATES: list[tuple[int, str, str]] = [
    (60, "2006-09-01", "2009-08-31"),  # LX
    (61, "2009-09-01", "2012-08-31"),  # LXI
    (62, "2012-09-01", "2015-08-31"),  # LXII
    (63, "2015-09-01", "2018-08-31"),  # LXIII
    (64, "2018-09-01", "2021-08-31"),  # LXIV
    (65, "2021-09-01", "2024-08-31"),  # LXV
    (66, "2024-09-01", "2027-08-31"),  # LXVI
]

# Compilar regex fuera del loop para rendimiento
_RE_LEGISLATURE = re.compile(r"([IVXLCDM]+)\s+LEGISLATURA", re.IGNORECASE)
_RE_YEAR = re.compile(r"(\w+)\s+AÑO\s+DE\s+EJERCICIO", re.IGNORECASE)
_RE_PERIOD = re.compile(r"(\w+)\s+PERIODO(?:\s+ORDINARIO)?", re.IGNORECASE)
_RE_DATE = re.compile(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})")
_RE_SENADOR_ID = re.compile(r"/votaciones/(\d+)")
_RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_SEN_PREFIX = re.compile(r"^Sen\.\s*")
_RE_SENADORA_PREFIX = re.compile(r"^Senadora?\s+")
_RE_DIGIT = re.compile(r"(\d+)")


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------


def roman_to_int(s: str) -> int:
    """Convertir numeral romano a entero.  'LXIII' → 63."""
    s = s.upper().strip()
    total = 0
    for i in range(len(s)):
        val = ROMAN_MAP.get(s[i], 0)
        if i + 1 < len(s) and ROMAN_MAP.get(s[i + 1], 0) > val:
            total -= val
        else:
            total += val
    return total


def spanish_ordinal_to_int(s: str) -> int:
    """Convertir ordinal español a entero.  'TERCER' → 3."""
    s_lower = s.lower().strip()
    if s_lower in SPANISH_ORDINALS:
        return SPANISH_ORDINALS[s_lower]
    for key, val in SPANISH_ORDINALS.items():
        if key in s_lower:
            return val
    digit_match = _RE_DIGIT.search(s)
    return int(digit_match.group(1)) if digit_match else 0


def parse_spanish_date(text: str) -> str:
    """Parsear fecha en español a ISO.  'Jueves 22 de febrero de 2018' → '2018-02-22'."""
    match = _RE_DATE.search(text)
    if not match:
        return ""
    day = int(match.group(1))
    month_name = match.group(2).lower()
    year = int(match.group(3))
    month = SPANISH_MONTHS.get(month_name, 0)
    if month == 0:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def clean_senator_name(raw: str) -> str:
    """Limpiar nombre de senador.

    - Elimina prefijo 'Sen. ' / 'Senador '
    - Reordena 'Apellido, Nombre' → 'Nombre Apellido'

    Ejemplo: 'Sen. González Canto, Félix Arturo' → 'Félix Arturo González Canto'
    """
    name = _RE_SEN_PREFIX.sub("", raw.strip())
    name = _RE_SENADORA_PREFIX.sub("", name)
    if "," in name:
        parts = name.split(",", 1)
        last_name = parts[0].strip()
        first_name = parts[1].strip()
        return re.sub(r"\s+", " ", f"{first_name} {last_name}".strip())

    return re.sub(r"\s+", " ", name)


def infer_legislature(date_str: str) -> int | None:
    """Infer legislature number from an ISO date string using LEGISLATURE_DATES."""
    if not date_str:
        return None
    for leg_num, start, end in LEGISLATURE_DATES:
        if start <= date_str <= end:
            return leg_num
    return None


# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------


class VotacionesSpider(scrapy.Spider):
    """Spider de votaciones nominales del Senado de la República (LXVI)."""

    name = "votaciones"

    def __init__(self, max_id: int = 5000, ids: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_id = int(max_id)
        # Si se pasa ``ids`` como string comma-separated, usar esa lista explícita
        if ids:
            self.vote_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
        else:
            self.vote_ids = list(range(1, self.max_id + 1))

    def start_requests(self):
        base_url = "https://www.senado.gob.mx/66/votacion/"
        for vote_id in self.vote_ids:
            yield scrapy.Request(
                url=f"{base_url}{vote_id}",
                callback=self.parse,
                meta={"vote_id": vote_id, "impersonate": "chrome131"},
                dont_filter=True,
                errback=self.handle_error,
            )

    def handle_error(self, failure):
        """Manejar 404s y errores de red sin crash."""
        vote_id = failure.request.meta.get("vote_id", "?")
        self.logger.debug(f"Skipping vote ID {vote_id}: {failure.value}")

    # ------------------------------------------------------------------
    # Helpers de parsing interno
    # ------------------------------------------------------------------

    def _parse_temporal_from_text(
        self,
        text: str,
        legislature: int | None,
        year: int | None,
        period: int | None,
        date_str: str | None,
    ) -> tuple[int | None, int | None, int | None, str | None]:
        """Intentar extraer datos temporales de un fragmento de texto plano."""
        if legislature is None:
            leg_match = _RE_LEGISLATURE.search(text)
            if leg_match:
                legislature = roman_to_int(leg_match.group(1))

        if year is None:
            year_match = _RE_YEAR.search(text)
            if year_match:
                year = spanish_ordinal_to_int(year_match.group(1))

        if period is None:
            period_match = _RE_PERIOD.search(text)
            if period_match:
                period = spanish_ordinal_to_int(period_match.group(1))

        if date_str is None:
            if _RE_DATE.search(text):
                date_str = parse_spanish_date(text)

        return legislature, year, period, date_str

    def _parse_temporal_data(self, response: Response) -> tuple[int | None, int | None, int | None, str | None]:
        """Extraer legislatura, año, periodo y fecha del HTML de la votación.

        Busca en <strong> elements (texto directo y HTML con <br>).
        """
        legislature: int | None = None
        year: int | None = None
        period: int | None = None
        date_str: str | None = None

        # 1) Texto directo de nodos <strong>
        for text in response.xpath("//strong/text()").getall():
            text = text.strip()
            if not text:
                continue
            legislature, year, period, date_str = self._parse_temporal_from_text(
                text, legislature, year, period, date_str
            )

        # 2) HTML completo de <strong> (contiene <br> que separan fragmentos)
        if legislature is None or year is None or period is None or date_str is None:
            for html in response.xpath("//strong").getall():
                fragments = _RE_BR.split(html)
                for fragment in fragments:
                    clean = _RE_TAG.sub("", fragment).strip()
                    if not clean:
                        continue
                    legislature, year, period, date_str = self._parse_temporal_from_text(
                        clean, legislature, year, period, date_str
                    )

        return legislature, year, period, date_str

    # ------------------------------------------------------------------
    # Parse principal
    # ------------------------------------------------------------------

    def parse(self, response: Response):
        vote_id: int = response.meta["vote_id"]

        # --- Datos temporales (siempre intentar, incluso sin viewTable) ---
        legislature, year, period, date_str = self._parse_temporal_data(response)

        if legislature is None:
            legislature = infer_legislature(date_str)

        # --- Siempre hacer AJAX request para obtener votos ---
        ajax_url = (
            "https://www.senado.gob.mx/66/app/votaciones/functions/viewTableVot.php"
        )
        yield scrapy.Request(
            url=ajax_url,
            callback=self.parse_votes,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": response.url,
            },
            body=f"action=ajax&cell=1&order=DESC&votacion={vote_id}&q=",
            meta={
                "vote_id": vote_id,
                "impersonate": "chrome131",
                "legislature": legislature,
                "year": year,
                "period": period,
                "date_str": date_str,
                "source_url": response.url,
            },
            dont_filter=True,
            errback=self.handle_error,
        )

    def parse_votes(self, response: Response):
        """Parsear votos nominales del HTML retornado por el endpoint AJAX.

        También decide si yield VotacionItem: si el AJAX devuelve votos,
        o si legislature fue resuelta, la votación es válida.
        Si no hay votos Y legislature es None, se descarta silenciosamente.
        """
        vote_id: int = response.meta["vote_id"]
        legislature: int | None = response.meta["legislature"]
        year: int | None = response.meta["year"]
        period: int | None = response.meta["period"]
        date_str: str | None = response.meta["date_str"]
        source_url: str = response.meta["source_url"]

        # --- Parsear votos primero ---
        votos: list[VotoNominalItem] = []
        for row in response.xpath("//tr"):
            cells = row.xpath(".//td")
            if len(cells) < 4:
                continue

            raw_name: str = row.xpath(".//td[2]//a/text()").get("")
            if not raw_name:
                continue

            nombre: str = clean_senator_name(raw_name)
            partido: str = (row.xpath(".//td[3]//a/text()").get("") or "").strip()
            voto_parts: list[str] = row.xpath(".//td[4]//text()").getall()
            voto_raw: str = " ".join(p.strip() for p in voto_parts if p.strip())
            voto: str = re.sub(r"\s+", " ", voto_raw.strip())

            href: str = (
                row.xpath(".//td[2]//a/@href").get("")
                or row.xpath(".//td[3]//a/@href").get("")
            )
            senador_match = _RE_SENADOR_ID.search(href)
            senador_id: int = int(senador_match.group(1)) if senador_match else 0

            if senador_id and nombre:
                votos.append(VotoNominalItem(
                    votacion_id=vote_id,
                    senador_id=senador_id,
                    nombre=nombre,
                    partido=partido,
                    voto=voto,
                ))

        # --- Decisión: ¿hay datos válidos? ---
        has_votes = len(votos) > 0
        has_legislature = legislature is not None

        if not has_votes and not has_legislature:
            # Descartar silenciosamente — votación vacía sin metadata
            return

        # --- Yield VotacionItem primero (FK constraint) ---
        yield VotacionItem(
            id=vote_id,
            legislature=legislature or 0,
            year=year or 0,
            period=period or 0,
            date=date_str or "",
            url=source_url,
        )

        # --- Yield votos nominales ---
        yield from votos
