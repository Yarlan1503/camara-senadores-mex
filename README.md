# Cámara de Senadores de México — Scraper

> **Estado del repositorio**: antecedente legacy / snapshot de referencia. Este
> proyecto se conserva para trazabilidad histórica y reproducibilidad del
> scraper del Senado; **no es la base activa de desarrollo** del Observatorio
> Congreso México.

Spider Scrapy para extraer datos de votaciones nominales y perfiles de senadores del [portal del Senado de la República](https://www.senado.gob.mx/66/).

## Datos extraídos

### Votaciones (IDs 1–5000)

Para cada votación se extrae:
- **Metadata temporal**: legislatura (LX–LXVI), año de ejercicio, periodo, fecha
- **Votos nominales**: senador, partido, sentido del voto (PRO/CONTRA/ABSTENCIÓN/AUSENTE), ID del senador

Fuente: `https://www.senado.gob.mx/66/votacion/{ID}`

`votos_nominales` registra votos nominales de **senadores** (`Sen.`). No es
un espejo del total bruto del AJAX oficial cuando ese fragmento mezcla filas de
otros cargos (por ejemplo `Dip.`); en esos casos, que el conteo local sea menor
al AJAX bruto no implica pérdida si coincide con el subconjunto `Sen.` auditado.

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

### Validación offline y dataset local

Los checks de mantenimiento no requieren red ni ejecutan spiders:

```bash
# Tests unitarios/offline
uv run pytest

# Si el entorno ya tiene dependencias resueltas y se quiere bloquear acceso a red de paquetes
uv run --offline pytest

# Validador read-only contra el snapshot local
uv run python scripts/validate_dataset.py --db senado.db
```

El validador abre la base con SQLite URI `mode=ro`, por lo que no modifica `senado.db`. El argumento `--db` tiene prioridad sobre cualquier configuración de entorno.

`SENADO_DB_PATH` permite apuntar el scraper, helpers de DB y validador a una base SQLite alternativa sin mover `senado.db`:

```bash
SENADO_DB_PATH=/ruta/a/otra/senado.db uv run python scripts/validate_dataset.py
```

Si no se pasa `--db` ni `SENADO_DB_PATH`, el proyecto usa `./senado.db` como ruta por defecto.

### Contrato auditado del dataset

El contrato actual del validador para el snapshot auditado espera, entre otros conteos, `454,094` filas en `votos_nominales` y `737` IDs distintos de senadores presentes en esa tabla. Ese total es el subconjunto nominal de senadores (`Sen.`), no el total bruto del AJAX oficial si incluye filas `Dip.`; los casos auditados 891, 3450 y 4890 siguen este criterio. Esto convive con la historia previa del knowledge graph que registraba `728` senadores únicos; esa cifra histórica no debe borrarse ni reescribirse sin contexto, porque pertenece a una observación previa del proyecto. Para cierre/verificación del snapshot actual, prevalece el contrato documentado en `scripts/validate_dataset.py`.

Warnings aceptados por el contrato actual:

- **Perfiles faltantes**: algunos IDs presentes en votos no tienen fila en `senadores` porque el portal `/66/` solo expone perfiles vigentes.
- **Votos o partidos vacíos**: existen valores vacíos heredados del dato fuente/snapshot y se reportan como advertencia, no como fallo.
- **Votaciones sin votos**: ciertas votaciones existen en metadata pero no tienen votos nominales asociados; el validador las lista como advertencia aceptada.

## Hallazgos técnicos

- El sitio carga votos nominales vía AJAX (`viewTableVot.php`), no en HTML estático
- WAF Incapsula bloquea Scrapy vanilla tras ~8 requests. `scrapy-impersonate` con TLS fingerprinting lo resuelve
- En votaciones de LXV/LXVI, la legislatura puede estar ausente del HTML — se infiere desde la fecha
- El portal genera dos formatos de página (con/sin `div#viewTable`), pero ambas tienen datos vía AJAX
- Algunos votos contienen texto en múltiples nodos HTML (ej: "AUSENTE COMISIÓN OFICIAL")

## Licencia

GNU General Public License v3.0 — ver [LICENSE](LICENSE).
