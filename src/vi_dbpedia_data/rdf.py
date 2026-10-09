"""Map processed country records to RDF, with links to English DBpedia and Wikidata.

Writes the instance graph `data/rdf/countries.ttl` and its VoID description
`data/rdf/void.ttl` (licence, statistics, linksets). Classes and properties are
declared in `ontology/vi-dbpedia.ttl`.
"""

from collections import Counter
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, PROV, RDF, RDFS, VOID, XSD

from vi_dbpedia_data.links import dbpedia_candidate, load_link_checks, resolve_sameas
from vi_dbpedia_data.models import CountryRecord, ResourceRef
from vi_dbpedia_data.utils import ROOT, canonical_title, read_json, wiki_iri_name

DBO = Namespace("http://dbpedia.org/ontology/")
DBR = Namespace("http://dbpedia.org/resource/")
VIR = Namespace("http://vi.dbpedia.org/resource/")
VIO = Namespace("http://vi.dbpedia.org/ontology/")
VIV = Namespace("http://vi.dbpedia.org/void/")
WD = Namespace("http://www.wikidata.org/entity/")
LICENSE = URIRef("https://creativecommons.org/licenses/by-sa/4.0/")
SPARQL_ENDPOINT = URIRef("http://localhost:3030/vi-dbpedia/sparql")

#: Record field -> (object property, the property's DBpedia range, text fallback).
RESOURCE_FIELDS = {
    "capital": (DBO.capital, DBO.City, VIO.capitalName),
    "currencies": (DBO.currency, DBO.Currency, VIO.currencyName),
    "official_languages": (DBO.officialLanguage, DBO.Language, VIO.officialLanguageName),
}
#: Linked dataset -> (homepage, resource IRI space, SPARQL endpoint).
LINK_TARGETS = {
    "dbpedia_en": ("https://dbpedia.org/", str(DBR), "https://dbpedia.org/sparql"),
    "wikidata": ("https://www.wikidata.org/", str(WD), "https://query.wikidata.org/sparql"),
}


def resource_uri(title: str) -> URIRef:
    """Vietnamese DBpedia IRI for a vi Wikipedia page title, e.g. vir:Việt_Nam."""
    return VIR[wiki_iri_name(title)]


def _new_graph() -> Graph:
    graph = Graph()
    for prefix, namespace in {
        "dbo": DBO,
        "dbr": DBR,
        "vir": VIR,
        "vio": VIO,
        "viv": VIV,
        "wd": WD,
        "owl": OWL,
        "rdfs": RDFS,
        "foaf": FOAF,
        "prov": PROV,
        "dct": DCTERMS,
        "void": VOID,
    }.items():
        graph.bind(prefix, namespace, override=True, replace=True)
    return graph


def _add_reference(graph: Graph, subject: URIRef, ref: ResourceRef, field: str) -> None:
    prop, range_class, text_prop = RESOURCE_FIELDS[field]
    if not ref.wiki_title:
        # An unlinked infobox value names no resource: keep it as text, not as
        # a literal object of an owl:ObjectProperty.
        graph.add((subject, text_prop, Literal(ref.label_vi, lang="vi")))
        return
    target = resource_uri(ref.wiki_title)
    graph.add((subject, prop, target))
    # Typed by the DBpedia range of the property and labelled with the page
    # title (one label per resource, as in DBpedia), not the varying link text.
    graph.add((target, RDF.type, range_class))
    graph.add((target, RDFS.label, Literal(canonical_title(ref.wiki_title), lang="vi")))


def build_graph(
    records: list[CountryRecord], link_checks: dict[str, dict[str, str]]
) -> tuple[Graph, Counter]:
    """Instance graph and a count of English DBpedia link statuses."""
    graph = _new_graph()
    link_status: Counter = Counter()
    for record in records:
        subject = resource_uri(record.title_vi)
        graph.add((subject, RDF.type, DBO.Country))
        graph.add((subject, RDFS.label, Literal(record.title_vi, lang="vi")))
        if record.abstract_vi:
            graph.add((subject, DBO.abstract, Literal(record.abstract_vi, lang="vi")))
        graph.add((subject, FOAF.isPrimaryTopicOf, URIRef(record.source_url)))
        graph.add((subject, DBO.wikiPageID, Literal(record.page_id, datatype=XSD.integer)))
        if record.revision_id is not None:
            graph.add(
                (subject, DBO.wikiPageRevisionID, Literal(record.revision_id, datatype=XSD.integer))
            )
            # The exact revision the values were extracted from.
            revision = f"https://vi.wikipedia.org/w/index.php?oldid={record.revision_id}"
            graph.add((subject, PROV.wasDerivedFrom, URIRef(revision)))

        target, status = resolve_sameas(dbpedia_candidate(record), link_checks)
        link_status[status] += 1
        if target:
            graph.add((subject, OWL.sameAs, URIRef(target)))
        if record.wikidata_id:
            # pageprops QID of the vi article itself, not a discovery hint.
            graph.add((subject, OWL.sameAs, WD[record.wikidata_id]))

        for field in RESOURCE_FIELDS:
            for ref in getattr(record, field):
                _add_reference(graph, subject, ref, field)
        if record.population_total is not None:
            graph.add(
                (
                    subject,
                    DBO.populationTotal,
                    Literal(record.population_total, datatype=XSD.nonNegativeInteger),
                )
            )
        if record.area_km2 is not None:
            # DBpedia stores dbo:areaTotal in square metres.
            area_m2 = record.area_km2 * 1_000_000
            graph.add((subject, DBO.areaTotal, Literal(area_m2, datatype=XSD.double)))
        for code in record.calling_codes:
            graph.add((subject, VIO.callingCode, Literal(code, datatype=XSD.string)))
    return graph, link_status


def build_void(graph: Graph, records: list[CountryRecord]) -> Graph:
    """VoID description: licence, provenance, statistics and linksets."""
    void = _new_graph()
    dataset = VIV.Dataset
    void.add((dataset, RDF.type, VOID.Dataset))
    void.add((dataset, DCTERMS.title, Literal("Vietnamese DBpedia: quốc gia", lang="vi")))
    void.add((dataset, DCTERMS.title, Literal("Vietnamese DBpedia: countries", lang="en")))
    void.add(
        (
            dataset,
            DCTERMS.description,
            Literal(
                "Dữ liệu quốc gia trích xuất từ hộp thông tin Wikipedia tiếng Việt, "
                "liên kết tới English DBpedia và Wikidata.",
                lang="vi",
            ),
        )
    )
    # Wikipedia text is CC BY-SA 4.0; derived data must keep the same licence.
    void.add((dataset, DCTERMS.license, LICENSE))
    void.add((dataset, DCTERMS.source, URIRef("https://vi.wikipedia.org/")))
    if records:
        latest = max(record.retrieved_at for record in records).date()
        void.add((dataset, DCTERMS.modified, Literal(latest, datatype=XSD.date)))
    void.add((dataset, VOID.uriSpace, Literal(str(VIR))))
    void.add((dataset, VOID.sparqlEndpoint, SPARQL_ENDPOINT))
    void.add((dataset, VOID.vocabulary, URIRef(str(DBO))))
    void.add((dataset, VOID.vocabulary, URIRef(str(VIO))))
    void.add((dataset, VOID.exampleResource, resource_uri("Việt Nam")))
    void.add((dataset, VOID.triples, Literal(len(graph))))
    void.add((dataset, VOID.entities, Literal(len(set(graph.subjects(RDF.type, None))))))
    void.add((dataset, VOID.distinctSubjects, Literal(len(set(graph.subjects())))))
    void.add((dataset, VOID.properties, Literal(len(set(graph.predicates())))))
    classes = Counter(graph.objects(None, RDF.type))
    void.add((dataset, VOID.classes, Literal(len(classes))))
    for cls, count in sorted(classes.items()):
        partition = VIV[f"Dataset_class_{cls.removeprefix(str(DBO))}"]
        void.add((dataset, VOID.classPartition, partition))
        void.add((partition, VOID["class"], cls))
        void.add((partition, VOID.entities, Literal(count)))

    for name, (homepage, uri_space, endpoint) in LINK_TARGETS.items():
        target = VIV[name]
        void.add((target, RDF.type, VOID.Dataset))
        void.add((target, FOAF.homepage, URIRef(homepage)))
        void.add((target, VOID.uriSpace, Literal(uri_space)))
        void.add((target, VOID.sparqlEndpoint, URIRef(endpoint)))
        linkset = VIV[f"Linkset_{name}"]
        links = sum(1 for _, o in graph.subject_objects(OWL.sameAs) if str(o).startswith(uri_space))
        void.add((linkset, RDF.type, VOID.Linkset))
        void.add((linkset, VOID.subjectsTarget, dataset))
        void.add((linkset, VOID.objectsTarget, target))
        void.add((linkset, VOID.linkPredicate, OWL.sameAs))
        void.add((linkset, VOID.triples, Literal(links)))
        void.add((dataset, VOID.subset, linkset))
    return void


def generate_rdf(root: Path = ROOT) -> dict:
    records = [
        CountryRecord.model_validate(item)
        for item in read_json(root / "data/processed/countries.json")
    ]
    graph, link_status = build_graph(records, load_link_checks(root))
    out = root / "data/rdf"
    out.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=out / "countries.ttl", format="turtle", encoding="utf-8")
    build_void(graph, records).serialize(
        destination=out / "void.ttl", format="turtle", encoding="utf-8"
    )
    return {
        "countries": len(records),
        "triples": len(graph),
        "subjects": len(set(graph.subjects())),
        "dbpedia_link_status": dict(sorted(link_status.items())),
        "wikidata_links": sum(1 for record in records if record.wikidata_id),
    }
