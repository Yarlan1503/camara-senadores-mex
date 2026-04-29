from pathlib import Path

from scrapy.http import HtmlResponse, Request, TextResponse

from senado_scrapy.items import VotacionItem, VotoNominalItem
from senado_scrapy.spiders.votaciones import VotacionesSpider, clean_senator_name, infer_legislature


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _html_response(html: str, *, vote_id: int = 5001, url: str | None = None) -> HtmlResponse:
    request = Request(url or f"https://www.senado.gob.mx/66/votacion/{vote_id}", meta={"vote_id": vote_id})
    return HtmlResponse(request.url, body=html.encode("utf-8"), encoding="utf-8", request=request)


def _ajax_response(
    html: str,
    *,
    vote_id: int = 5001,
    legislature: int | None = 66,
    year: int | None = 1,
    period: int | None = 1,
    date_str: str | None = "2024-09-10",
    source_url: str = "https://www.senado.gob.mx/66/votacion/5001",
) -> TextResponse:
    request = Request(
        "https://www.senado.gob.mx/66/app/votaciones/functions/viewTableVot.php",
        meta={
            "vote_id": vote_id,
            "legislature": legislature,
            "year": year,
            "period": period,
            "date_str": date_str,
            "source_url": source_url,
        },
    )
    return TextResponse(request.url, body=html.encode("utf-8"), encoding="utf-8", request=request)


def test_infer_legislature_by_date_p1():
    assert infer_legislature("2018-02-22") == 63
    assert infer_legislature("2024-09-01") == 66
    assert infer_legislature("") is None


def test_period_is_flexible_without_ordinario_p2():
    spider = VotacionesSpider(ids="5001")
    response = _html_response(_fixture("votacion_page_viewtable.html"))

    legislature, year, period, date_str = spider._parse_temporal_data(response)

    assert legislature == 63
    assert year == 3
    assert period == 2
    assert date_str == "2018-02-22"


def test_multinode_vote_keeps_ausente_comision_oficial_p3():
    spider = VotacionesSpider(ids="5001")
    response = _ajax_response(_fixture("votes_ajax.html"))

    items = list(spider.parse_votes(response))
    votes = [item for item in items if isinstance(item, VotoNominalItem)]

    assert votes[1]["voto"] == "AUSENTE COMISIÓN OFICIAL"


def test_internal_spaces_are_normalized_in_names_p4():
    assert clean_senator_name("Sen.  González   Canto,   Félix   Arturo") == "Félix Arturo González Canto"

    spider = VotacionesSpider(ids="5001")
    response = _ajax_response(_fixture("votes_ajax.html"))
    items = list(spider.parse_votes(response))
    votes = [item for item in items if isinstance(item, VotoNominalItem)]

    assert votes[0]["nombre"] == "Félix Arturo González Canto"
    assert votes[1]["nombre"] == "María Luisa López Hernández"


def test_parse_page_with_viewtable_produces_ajax_request():
    spider = VotacionesSpider(ids="5001")
    response = _html_response(_fixture("votacion_page_viewtable.html"), vote_id=5001)

    results = list(spider.parse(response))

    assert len(results) == 1
    ajax_request = results[0]
    assert isinstance(ajax_request, Request)
    assert ajax_request.url == "https://www.senado.gob.mx/66/app/votaciones/functions/viewTableVot.php"
    assert ajax_request.callback == spider.parse_votes
    assert ajax_request.method == "POST"
    assert b"votacion=5001" in ajax_request.body
    assert ajax_request.meta["legislature"] == 63
    assert ajax_request.meta["period"] == 2
    assert ajax_request.meta["date_str"] == "2018-02-22"


def test_parse_page_without_viewtable_or_data_is_stable():
    spider = VotacionesSpider(ids="9999")
    response = _html_response(_fixture("votacion_page_no_viewtable.html"), vote_id=9999)

    results = list(spider.parse(response))

    assert len(results) == 1
    ajax_request = results[0]
    assert isinstance(ajax_request, Request)
    assert ajax_request.url.endswith("/viewTableVot.php")
    assert ajax_request.meta["legislature"] is None
    assert ajax_request.meta["year"] is None
    assert ajax_request.meta["period"] is None
    assert ajax_request.meta["date_str"] is None


def test_parse_votes_yields_metadata_and_votes_when_ajax_has_rows():
    spider = VotacionesSpider(ids="5001")
    response = _ajax_response(_fixture("votes_ajax.html"), vote_id=5001, legislature=66)

    items = list(spider.parse_votes(response))

    votaciones = [item for item in items if isinstance(item, VotacionItem)]
    votes = [item for item in items if isinstance(item, VotoNominalItem)]

    assert len(votaciones) == 1
    assert votaciones[0]["id"] == 5001
    assert votaciones[0]["legislature"] == 66
    assert len(votes) == 2


def test_parse_votes_discards_empty_ajax_without_legislature():
    spider = VotacionesSpider(ids="5001")
    response = _ajax_response("<table><tbody></tbody></table>", legislature=None, year=None, period=None, date_str=None)

    assert list(spider.parse_votes(response)) == []


def test_parse_votes_keeps_metadata_only_when_legislature_exists_without_rows():
    spider = VotacionesSpider(ids="5001")
    response = _ajax_response("<table><tbody></tbody></table>", legislature=66)

    items = list(spider.parse_votes(response))

    assert len(items) == 1
    assert isinstance(items[0], VotacionItem)
    assert items[0]["legislature"] == 66
