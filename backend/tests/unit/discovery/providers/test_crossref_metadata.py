import httpx

from app.core.config import Settings
from app.modules.papers.schemas.paper import RawPaperRecord
from app.modules.discovery.schemas import SearchQuery
from app.platform.http import client as source_http
from app.modules.discovery.providers.crossref import CrossrefAdapter, _pdf_link
from app.modules.discovery.providers.normalizer import Normalizer
from app.shared.text import clean_metadata_text


def test_jats_metadata_is_readable_without_rendering_tags_or_scripts():
    title = 'Effect of <i>Borassus flabellifer</i>\n on growth &amp; yield'
    abstract = '<jats:p>We measured <jats:italic>plant</jats:italic> growth.</jats:p><jats:p>Yield &gt; control.</jats:p>'
    assert clean_metadata_text(title) == 'Effect of Borassus flabellifer on growth & yield'
    assert clean_metadata_text(abstract) == 'We measured plant growth. Yield > control.'
    assert clean_metadata_text('<script>do not show</script><jats:p>Safe text</jats:p>') == 'Safe text'
    assert clean_metadata_text('<jats:p>  </jats:p>') is None


async def test_crossref_reads_abstract_pdf_and_clean_title(monkeypatch):
    data = {
        'title': ['Study of <i>Borassus flabellifer</i>\n extracts'],
        'abstract': '<jats:abstract><jats:p>Evidence &amp; results.</jats:p></jats:abstract>',
        'author': [{'given': 'Vinduja', 'family': 'Vasudevan'}],
        'DOI': '10.1039/d3ay00704a',
        'link': [
            {'URL': 'https://publisher.example/landing', 'content-type': 'text/html', 'intended-application': 'text-mining'},
            {'URL': 'https://publisher.example/pdf', 'content-type': 'application/pdf', 'intended-application': 'text-mining'},
        ],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'message': {'items': [data]}}))) as client:
        monkeypatch.setattr(source_http, 'get_source_client', lambda: client)
        records = await CrossrefAdapter(Settings(_env_file=None)).search(SearchQuery(query='paper', limit=1))
    assert len(records) == 1
    assert records[0].title == 'Study of Borassus flabellifer extracts'
    assert records[0].abstract == 'Evidence & results.'
    assert records[0].pdf_url == 'https://publisher.example/pdf'
    assert records[0].authors == ['Vinduja Vasudevan']
    assert records[0].raw_payload['abstract'] == data['abstract']


def test_crossref_does_not_treat_version_of_record_as_open_access():
    links = [
        {'URL': 'https://publisher.example/unspecified', 'content-type': 'unspecified', 'intended-application': 'similarity-checking', 'content-version': 'vor'},
        {'URL': 'https://publisher.example/landing', 'content-type': 'text/html', 'intended-application': 'text-mining'},
        {'URL': 'http://publisher.example/pdf', 'content-type': 'application/pdf', 'intended-application': 'text-mining'},
        {'URL': 'https://publisher.example/restricted', 'content-type': 'application/pdf', 'content-version': 'vor'},
    ]
    assert _pdf_link(links) == 'https://publisher.example/unspecified'
    assert _pdf_link(links[1:]) is None


def test_normalizer_cleans_titles_and_abstracts_from_all_sources():
    records = [
        RawPaperRecord(source='openalex', title='A <i>marked</i>\n title', abstract='<jats:p>A &amp; B.</jats:p>'),
        RawPaperRecord(source='crossref', title='<i> </i>'),
    ]
    papers = Normalizer().normalize(records)
    assert len(papers) == 1
    assert papers[0].title == 'A marked title'
    assert papers[0].abstract == 'A & B.'
