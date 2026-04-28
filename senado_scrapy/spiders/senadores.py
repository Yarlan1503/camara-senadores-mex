"""Spider to scrape senator profiles from the Mexican Senate website."""

from __future__ import annotations

import re

import scrapy
from scrapy.http import Response

from senado_scrapy.db import get_connection
from senado_scrapy.items import SenadorItem


def parse_tipo_eleccion(raw: str) -> str:
    """Extract election type from the tipoEleccion heading text.

    Examples:
        'Senador Electo por el Principio de Mayoría Relativa' → 'Mayoría Relativa'
        'Senadora Electa de Representación Proporcional' → 'Representación Proporcional'
    """
    if not raw:
        return ""

    # Match "Principio de [tipo]"
    match = re.search(r"Principio\s+de\s+(.+?)$", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Match "Primera Minoría" (e.g. "Senador Electo de Primera Minoría")
    match = re.search(r"(Primera\s+Minor[ií]a)", raw, re.IGNORECASE)
    if match:
        return "Primera Minoría"

    # Match "Representación Proporcional"
    match = re.search(r"(Representaci[oó]n\s+Proporcional)", raw, re.IGNORECASE)
    if match:
        return "Representación Proporcional"

    # Match "Lista Nacional"
    match = re.search(r"(Lista\s+Nacional)", raw, re.IGNORECASE)
    if match:
        return "Lista Nacional"

    # Fallback: return cleaned text
    return raw.strip()


_RE_SENADOR_PREFIX = re.compile(r"^Senador\s+", re.IGNORECASE)
_RE_SENADORA_PREFIX = re.compile(r"^Senadora\s+", re.IGNORECASE)


def _parse_name_and_sex(raw_name: str) -> tuple[str, str | None]:
    """Parse senator name and infer sex from the prefix.

    'Senador José Antonio Aguilar Bodegas' → ('José Antonio Aguilar Bodegas', 'Hombre')
    'Senadora Micaela Aguilar González' → ('Micaela Aguilar González', 'Mujer')
    """
    if not raw_name:
        return "", None

    sexo: str | None = None

    if _RE_SENADORA_PREFIX.match(raw_name):
        sexo = "Mujer"
        nombre = re.sub(r"\s+", " ", _RE_SENADORA_PREFIX.sub("", raw_name).strip())
    elif _RE_SENADOR_PREFIX.match(raw_name):
        sexo = "Hombre"
        nombre = re.sub(r"\s+", " ", _RE_SENADOR_PREFIX.sub("", raw_name).strip())
    else:
        nombre = re.sub(r"\s+", " ", raw_name.strip())

    return nombre, sexo


class SenadoresSpider(scrapy.Spider):
    """Scrape senator profile pages using IDs from the votos_nominales table."""

    name = "senadores"

    def start_requests(self) -> list[scrapy.Request]:
        """Get senator IDs from votos_nominales that don't exist in senadores yet."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT DISTINCT vn.senador_id
                FROM votos_nominales vn
                LEFT JOIN senadores s ON vn.senador_id = s.id
                WHERE s.id IS NULL
                ORDER BY vn.senador_id
                """
            )
            senador_ids: list[int] = [row["senador_id"] for row in cursor.fetchall()]
            self.logger.info(f"Found {len(senador_ids)} senator IDs to scrape")
        finally:
            conn.close()

        base_url = "https://www.senado.gob.mx/66/senador/"
        for sid in senador_ids:
            yield scrapy.Request(
                url=f"{base_url}{sid}",
                callback=self.parse,
                meta={"senador_id": sid},
                dont_filter=True,
                errback=self.handle_error,
            )

    def handle_error(self, failure: object) -> None:
        """Log and skip failed requests (404s, timeouts, etc.)."""
        sid = failure.request.meta.get("senador_id", "?")  # type: ignore[attr-defined]
        self.logger.debug(f"Skipping senator ID {sid}: {failure.value}")  # type: ignore[attr-defined]

    def parse(self, response: Response) -> scrapy.Item:
        """Parse a senator profile page."""
        senador_id: int = response.meta["senador_id"]

        # Check if page has valid content — look for SectioninfoSenador
        section = response.xpath('//section[contains(@class, "SectioninfoSenador")]')
        if not section:
            self.logger.debug(f"No profile data for senator ID {senador_id}")
            return None  # type: ignore[return-value]

        # --- Extract nombre from <h2 class="nSenador"> ---
        raw_name: str = (
            response.xpath('//h2[contains(@class, "nSenador")]/text()').get("") or ""
        ).strip()
        nombre, sexo = _parse_name_and_sex(raw_name)

        # --- Extract tipo de elección ---
        tipo_raw: str = response.xpath(
            '//h3[contains(@class, "tipoEleccion")]/text()'
        ).get("")
        tipo_eleccion: str = parse_tipo_eleccion(tipo_raw)

        # --- Extract estado ---
        estado: str = ""
        estado_raw: str = response.xpath(
            '//h4[contains(@class, "nEstadi")]/text()'
        ).get("")
        if estado_raw:
            estado = estado_raw.strip()

        yield SenadorItem(
            id=senador_id,
            nombre=nombre,
            sexo=sexo,
            tipo_eleccion=tipo_eleccion,
            estado=estado,
            url=response.url,
        )
