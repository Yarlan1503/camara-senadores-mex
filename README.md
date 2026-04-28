# Cámara de Senadores de México — Scraper

Spider Scrapy para extraer datos de votaciones nominales y perfiles de senadores del [portal del Senado de la República](https://www.senado.gob.mx/66/).

## Datos extraídos

### Votaciones (IDs 1–5000)

Para cada votación se extrae:
- **Metadata temporal**: legislatura (LX–LXVI), año de ejercicio, periodo, fecha
- **Votos nominales**: senador, partido, sentido del voto (PRO/CONTRA/ABSTENCIÓN/AUSENTE), ID del senador

Fuente: `https://www.senado.gob.mx/66/votacion/{ID}`

### Senadores

Para cada senador (IDs extraídos de las votaciones):
- **Perfil**: nombre, sexo, tipo de elección, estado representado

Fuente: `https://www.senado.gob.mx/66/senador/{ID}`

> **Nota**: El portal `/66/` solo sirve perfiles de la legislatura vigente (LXVI). Senadores de legislaturas anteriores no tienen perfil accesible.

## Stack

- **Python** — ecosistema Astral (uv, ruff)
- **Scrapy** + **scrapy-impersonate** (TLS fingerprinting para evadir WAF Incapsula)
- **SQLite** (WAL mode)

## Schema (SQLite)

```
votaciones      → id, legislature, year, period, date, url, scraped_at
votos_nominales → id, votacion_id (FK), senador_id, nombre, partido, voto
senadores       → id, nombre, sexo, tipo_eleccion, estado, url, scraped_at
```

## Uso

```bash
# Instalar dependencias
uv sync

# Scrapear votaciones (IDs 1–5000)
uv run scrapy crawl votaciones -a max_id=5000 --logfile=logs/votaciones.log

# Scrapear votaciones específicas
uv run scrapy crawl votaciones -a ids=347,891,2103

# Scrapear perfiles de senadores (usa IDs de votos_nominales)
uv run scrapy crawl senadores --logfile=logs/senadores.log
```

## Hallazgos técnicos

- El sitio carga votos nominales vía AJAX (`viewTableVot.php`), no en HTML estático
- WAF Incapsula bloquea Scrapy vanilla tras ~8 requests. `scrapy-impersonate` con TLS fingerprinting lo resuelve
- En votaciones de LXV/LXVI, la legislatura puede estar ausente del HTML — se infiere desde la fecha
- El portal genera dos formatos de página (con/sin `div#viewTable`), pero ambas tienen datos vía AJAX
- Algunos votos contienen texto en múltiples nodos HTML (ej: "AUSENTE COMISIÓN OFICIAL")

## Licencia

GNU General Public License v3.0 — ver [LICENSE](LICENSE).
