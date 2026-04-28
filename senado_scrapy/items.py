"""Scrapy items for Mexican Senate data."""

import scrapy


class VotacionItem(scrapy.Item):
    """Votación (roll call vote) metadata."""

    id = scrapy.Field()  # URL ID (integer)
    legislature = scrapy.Field()  # e.g. 63 for LXIII
    year = scrapy.Field()  # Año de ejercicio (integer)
    period = scrapy.Field()  # Periodo ordinario (integer)
    date = scrapy.Field()  # ISO date string YYYY-MM-DD
    url = scrapy.Field()  # Full URL


class VotoNominalItem(scrapy.Item):
    """Individual vote within a votación."""

    votacion_id = scrapy.Field()  # FK to votaciones.id
    senador_id = scrapy.Field()  # Senator ID from href
    nombre = scrapy.Field()  # Senator name (reordered: "Félix Arturo González Canto")
    partido = scrapy.Field()  # Party acronym
    voto = scrapy.Field()  # Vote: PRO, CON, ABSTEN, AUSENTE, etc.


class SenadorItem(scrapy.Item):
    """Senator profile data."""

    id = scrapy.Field()  # Senator ID
    nombre = scrapy.Field()  # Full name
    sexo = scrapy.Field()  # "Hombre" / "Mujer" / None
    tipo_eleccion = scrapy.Field()  # e.g. "Mayoría Relativa", "Primera Minoría", "Representación Proporcional"
    estado = scrapy.Field()  # State represented
    url = scrapy.Field()  # Full URL
