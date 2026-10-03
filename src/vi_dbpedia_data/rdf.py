import json
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import FOAF, OWL, RDF, RDFS, XSD

from vi_dbpedia_data.models import CountryRecord

# Namespaces
DBO = Namespace("http://dbpedia.org/ontology/")
DBP = Namespace("http://dbpedia.org/property/")
EX = Namespace("http://vi.dbpedia.org/resource/")
EX_ONT = Namespace("http://vi.dbpedia.org/ontology/")


def encode_uri_component(text: str) -> str:
    """Encode string for URI, replacing spaces with underscores."""
    text_underscore = text.replace(" ", "_")
    return quote(text_underscore, safe=":,()")


def generate_rdf(input_path: Path, output_path: Path) -> None:
    """Generate RDF graph from processed JSON data and save as Turtle."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = [CountryRecord.model_validate(item) for item in data]

    g = Graph()
    g.bind("dbo", DBO)
    g.bind("dbp", DBP)
    g.bind("ex", EX)
    g.bind("ex_ont", EX_ONT)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("foaf", FOAF)

    for record in records:
        subject_title = encode_uri_component(record.title_vi)
        subject = EX[subject_title]

        g.add((subject, RDF.type, DBO.Country))
        g.add((subject, RDFS.label, Literal(record.title_vi, lang="vi")))

        if record.abstract_vi:
            g.add((subject, DBO.abstract, Literal(record.abstract_vi, lang="vi")))

        if record.source_url:
            g.add((subject, FOAF.isPrimaryTopicOf, URIRef(record.source_url)))

        if record.english_dbpedia_candidate:
            g.add((subject, OWL.sameAs, URIRef(record.english_dbpedia_candidate)))

        for cap in record.capital:
            if cap.wiki_title:
                cap_uri = EX[encode_uri_component(cap.wiki_title)]
                g.add((subject, DBO.capital, cap_uri))
                g.add((cap_uri, RDFS.label, Literal(cap.label_vi, lang="vi")))
            else:
                g.add((subject, DBO.capital, Literal(cap.label_vi, lang="vi")))

        for lang in record.official_languages:
            if lang.wiki_title:
                lang_uri = EX[encode_uri_component(lang.wiki_title)]
                g.add((subject, DBO.officialLanguage, lang_uri))
                g.add((lang_uri, RDFS.label, Literal(lang.label_vi, lang="vi")))
            else:
                g.add((subject, DBO.officialLanguage, Literal(lang.label_vi, lang="vi")))

        for cur in record.currencies:
            if cur.wiki_title:
                cur_uri = EX[encode_uri_component(cur.wiki_title)]
                g.add((subject, DBO.currency, cur_uri))
                g.add((cur_uri, RDFS.label, Literal(cur.label_vi, lang="vi")))
            else:
                g.add((subject, DBO.currency, Literal(cur.label_vi, lang="vi")))

        if record.population_total is not None:
            g.add(
                (
                    subject,
                    DBO.populationTotal,
                    Literal(record.population_total, datatype=XSD.integer),
                )
            )

        if record.area_km2 is not None:
            area_m2 = record.area_km2 * 1_000_000
            g.add((subject, DBO.areaTotal, Literal(area_m2, datatype=XSD.double)))

        for code in record.calling_codes:
            g.add((subject, DBO.callingCode, Literal(code, datatype=XSD.string)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(output_path), format="turtle", encoding="utf-8")
    print(f"Generated RDF graph with {len(g)} triples at {output_path}")


if __name__ == "__main__":
    generate_rdf(Path("data/processed/countries.json"), Path("data/rdf/countries.ttl"))

