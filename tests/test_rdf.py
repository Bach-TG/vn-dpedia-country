import json
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from vi_dbpedia_data.rdf import DBO, generate_rdf


@pytest.fixture
def sample_data(tmp_path):
    data = [
        {
            "page_id": 1,
            "title_vi": "Việt Nam",
            "abstract_vi": "Việt Nam là một quốc gia...",
            "source_url": "https://vi.wikipedia.org/wiki/Việt_Nam",
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
            "currencies": [{"label_vi": "Đồng", "wiki_title": "Đồng_(tiền)"}],
            "official_languages": [],
            "calling_codes": ["+84"],
        }
    ]

    input_path = tmp_path / "countries.json"
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return input_path


def test_generate_rdf(sample_data, tmp_path):
    output_path = tmp_path / "countries.ttl"
    generate_rdf(sample_data, output_path)

    assert output_path.exists()

    g = Graph()
    g.parse(output_path, format="turtle")

    # Check that we have exactly one country
    countries = list(g.subjects(RDF.type, DBO.Country))
    assert len(countries) == 1

    country_uri = countries[0]

    # Check population
    population = list(g.objects(country_uri, DBO.populationTotal))[0]
    assert population.value == 100000000

    # Check area
    area = list(g.objects(country_uri, DBO.areaTotal))[0]
    assert area.value == 331212.0 * 1_000_000

    # Check capital
    capitals = list(g.objects(country_uri, DBO.capital))
    assert len(capitals) == 1
    assert type(capitals[0]) == URIRef

