from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, VOID, XSD

from vi_dbpedia_data.links import LINK_CHECK_COLUMNS, LINK_CHECK_PATH
from vi_dbpedia_data.models import CountryRecord
from vi_dbpedia_data.rdf import DBO, VIO, VIR, build_graph, generate_rdf
from vi_dbpedia_data.utils import ROOT, read_json, write_csv, write_json

VIET_NAM = URIRef("http://vi.dbpedia.org/resource/Việt_Nam")
ONTOLOGY = ROOT / "ontology/vi-dbpedia.ttl"
# W3C/FOAF terms need no declaration in a domain ontology.
STANDARD_NAMESPACES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://xmlns.com/foaf/0.1/",
    "http://www.w3.org/ns/prov#",
)


def _record(**overrides) -> dict:
    record = {
        "page_id": 1,
        "title_vi": "Việt Nam",
        "abstract_vi": "Việt Nam là một quốc gia...",
        "source_url": "https://vi.wikipedia.org/wiki/Vi%E1%BB%87t_Nam",
        "revision_id": 123,
        "revision_timestamp": "2024-01-01T00:00:00Z",
        "retrieved_at": "2024-01-02T00:00:00Z",
        "wikidata_id": "Q881",
        "english_title": "Vietnam",
        "english_wikipedia_url": "https://en.wikipedia.org/wiki/Vietnam",
        "english_dbpedia_candidate": "http://dbpedia.org/resource/Vietnam",
        "capital": [{"label_vi": "Hà Nội", "wiki_title": "Hà Nội"}],
        "population_total": 100000000,
        "area_km2": 331212.0,
        "currencies": [{"label_vi": "Đồng", "wiki_title": None}],
        "official_languages": [{"label_vi": "tiếng Việt", "wiki_title": "tiếng_Việt"}],
        "calling_codes": ["+84"],
    }
    return record | overrides


@pytest.fixture
def root(tmp_path):
    write_json(tmp_path / "data/processed/countries.json", [_record()])
    return tmp_path


def test_generate_rdf(root):
    summary = generate_rdf(root)
    graph = Graph().parse(root / "data/rdf/countries.ttl", format="turtle")

    assert summary["triples"] == len(graph)
    assert list(graph.subjects(RDF.type, DBO.Country)) == [VIET_NAM]
    assert (VIET_NAM, RDFS.label, Literal("Việt Nam", lang="vi")) in graph
    assert (VIET_NAM, DBO.wikiPageID, Literal(1, datatype=XSD.integer)) in graph
    assert (
        VIET_NAM,
        PROV.wasDerivedFrom,
        URIRef("https://vi.wikipedia.org/w/index.php?oldid=123"),
    ) in graph
    assert graph.value(VIET_NAM, DBO.populationTotal).datatype == XSD.nonNegativeInteger
    assert graph.value(VIET_NAM, DBO.areaTotal).value == 331212.0 * 1_000_000
    assert (VIET_NAM, VIO.callingCode, Literal("+84", datatype=XSD.string)) in graph

    # Linked values are typed resources with one page-title label.
    capital = VIR["Hà_Nội"]
    assert (VIET_NAM, DBO.capital, capital) in graph
    assert (capital, RDF.type, DBO.City) in graph
    # `tiếng_Việt` and `Tiếng Việt` are the same page, hence the same IRI.
    language = VIR["Tiếng_Việt"]
    assert (VIET_NAM, DBO.officialLanguage, language) in graph
    assert (language, RDF.type, DBO.Language) in graph
    assert set(graph.objects(language, RDFS.label)) == {Literal("Tiếng Việt", lang="vi")}

    # Unlinked text is not the object of an owl:ObjectProperty.
    assert graph.value(VIET_NAM, DBO.currency) is None
    assert (VIET_NAM, VIO.currencyName, Literal("Đồng", lang="vi")) in graph

    # Without a link check, the interlanguage link is kept but reported unverified.
    assert summary["dbpedia_link_status"] == {"unverified": 1}
    assert set(graph.objects(VIET_NAM, OWL.sameAs)) == {
        URIRef("http://dbpedia.org/resource/Vietnam"),
        URIRef("http://www.wikidata.org/entity/Q881"),
    }


def test_void_describes_licence_statistics_and_linksets(root):
    generate_rdf(root)
    graph = Graph().parse(root / "data/rdf/countries.ttl", format="turtle")
    void = Graph().parse(root / "data/rdf/void.ttl", format="turtle")
    dataset = URIRef("http://vi.dbpedia.org/void/Dataset")

    assert (
        dataset,
        DCTERMS.license,
        URIRef("https://creativecommons.org/licenses/by-sa/4.0/"),
    ) in void
    assert void.value(dataset, VOID.triples).value == len(graph)
    linksets = {
        str(void.value(linkset, VOID.objectsTarget)): void.value(linkset, VOID.triples).value
        for linkset in void.objects(dataset, VOID.subset)
    }
    assert linksets == {
        "http://vi.dbpedia.org/void/dbpedia_en": 1,
        "http://vi.dbpedia.org/void/wikidata": 1,
    }


def test_link_check_corrects_sameas(root):
    records = [
        _record(),
        _record(page_id=2, title_vi="Đông Timor", english_title="Timor-Leste", wikidata_id=None),
        _record(page_id=3, title_vi="Gruzia", english_title="Georgia", wikidata_id=None),
    ]
    write_json(root / "data/processed/countries.json", records)
    checks = [
        {"dbpedia_uri": "http://dbpedia.org/resource/Vietnam", "status": "error"},
        {
            "dbpedia_uri": "http://dbpedia.org/resource/Timor-Leste",
            "status": "redirect_resolved",
            "sameas_uri": "http://dbpedia.org/resource/East_Timor",
        },
        {"dbpedia_uri": "http://dbpedia.org/resource/Georgia", "status": "disambiguation"},
    ]
    write_csv(root / LINK_CHECK_PATH, checks, LINK_CHECK_COLUMNS)

    summary = generate_rdf(root)
    graph = Graph().parse(root / "data/rdf/countries.ttl", format="turtle")

    assert summary["dbpedia_link_status"] == {
        "disambiguation": 1,
        "redirect_resolved": 1,
        "unverified": 1,
    }
    assert (
        VIR["Đông_Timor"],
        OWL.sameAs,
        URIRef("http://dbpedia.org/resource/East_Timor"),
    ) in graph
    assert graph.value(VIR["Gruzia"], OWL.sameAs) is None


def _project_graph() -> Graph:
    records = [
        CountryRecord.model_validate(item)
        for item in read_json(ROOT / "data/processed/countries.json")
    ]
    graph, _ = build_graph(records, {})
    return graph


def test_every_term_used_is_declared_in_the_ontology():
    ontology = Graph().parse(ONTOLOGY, format="turtle")
    declared = set(ontology.subjects(RDF.type, None))
    graph = _project_graph()
    used = set(graph.predicates()) | set(graph.objects(None, RDF.type))
    undeclared = {
        term
        for term in used
        if term not in declared and not str(term).startswith(STANDARD_NAMESPACES)
    }
    assert undeclared == set()


@pytest.mark.parametrize(
    "name", ["01_countries_by_class.rq", "02_population_filter.rq", "03_external_links.rq"]
)
def test_saved_queries_return_rows(name):
    query = (ROOT / "data/queries" / name).read_text("utf-8")
    rows = list(_project_graph().query(query))
    assert len(rows) > 0
    if name == "02_population_filter.rq":
        assert all(row.density is not None for row in rows if row.areaKm2 is not None)


def test_federated_query_targets_dbpedia():
    query = Path(ROOT / "data/queries/04_federated_dbpedia.rq").read_text("utf-8")
    assert "SERVICE <https://dbpedia.org/sparql>" in query
