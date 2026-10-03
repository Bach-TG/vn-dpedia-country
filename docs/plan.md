# Semantic Web Capstone Plan: A Vietnamese DBpedia Prototype

## Goal and scope

Build a small, reproducible Vietnamese Wikipedia knowledge graph, modeled on DBpedia. In one week, the group will define an ontology, collect and transform articles into RDF, link verified entities to English DBpedia, and expose the result through a SPARQL endpoint.

**Target:** 100–200 articles from one coherent domain (for example, Vietnamese people or places), with 5–8 useful fields. Choose the domain on day 1 after checking that a small sample has consistent information. This is a prototype, not a full Vietnamese DBpedia release.

**Minimum deliverables:** collection and transformation scripts, cleaned intermediate data, ontology, Turtle RDF dataset, documented external links, a local SPARQL endpoint, three working queries, README, short report, and demo.

## Team responsibilities

| Member | Responsibility | Output |
|---|---|---|
| 1 — Data | Collect Vietnamese Wikipedia articles; normalize titles and fields; record article URLs and English language links; inspect missing values. | Reproducible collection script, cleaned JSON/CSV, data summary. |
| 2 — Ontology and RDF | Define classes and properties; map records to RDF; validate RDF parsing and URI construction. | Ontology, Turtle dataset, RDF generation/validation scripts. |
| 3 — Query service | Configure Apache Jena Fuseki; load the graph; prepare and check SPARQL queries. | Local endpoint, setup instructions, sample `.rq` queries. |
| 4 — Integration and presentation | Set acceptance criteria, review examples and link quality, integrate outputs, write the report/README, and prepare the demo. | Quality summary, documentation, slides, rehearsed demo. |

All four members should review the five-record reference sample on day 1. Member 4 coordinates the interfaces and starts documentation immediately, rather than waiting for completed code.

## Data model and pipeline

1. **Collect:** Use the MediaWiki API to get articles and English language links. Keep the source URL and retrieval date.
2. **Clean:** Output one record per article using an agreed schema, for example `page_id`, `title_vi`, `abstract_vi`, `source_url`, `english_title`, and domain-specific fields. Record missing fields explicitly; do not guess values.
3. **Model:** Reuse DBpedia ontology classes and properties when they match the intended meaning. Add a small project namespace for any necessary custom properties. Use stable, encoded entity URIs and Vietnamese language tags (`@vi`).
4. **Transform:** Serialize records as Turtle. Include type, label, source article, and available domain properties.
5. **Link:** Derive a candidate English DBpedia URI from the English Wikipedia language link. Verify a sample and emit `owl:sameAs` only when the two resources refer to the same entity. Track uncertain or missing links separately.
6. **Serve:** Load the Turtle file into a local Fuseki dataset and query it through SPARQL.

An illustrative entity description (replace the example URI and properties with the team's final convention):

```turtle
@prefix ex: <https://example.org/vi-db/resource/> .
@prefix dbo: <http://dbpedia.org/ontology/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

ex:Ha_Noi a dbo:Place ;
    rdfs:label "Hà Nội"@vi ;
    foaf:isPrimaryTopicOf <https://vi.wikipedia.org/wiki/H%C3%A0_N%E1%BB%99i> ;
    owl:sameAs <http://dbpedia.org/resource/Hanoi> .
```

The illustrative `https://example.org/` namespace is a placeholder; document the actual URI policy before generating the final graph.

## Seven-day schedule

| Day | Work and checkpoint |
|---|---|
| 1 | Select the domain, 5–8 fields, URI convention, and intermediate record schema. Hand-build five reference records and agree on three demo questions. |
| 2 | Collect 20–30 articles; define the ontology; start the Fuseki dataset; draft README/report structure. |
| 3 | Complete an end-to-end run on the small batch: collection → cleaning → RDF → SPARQL. Fix schema and encoding issues before scaling up. |
| 4 | Expand to 100–200 records; add candidate English DBpedia links and a review log. |
| 5 | Validate RDF syntax, entity/property counts, missing values, and 15–20 manually reviewed links; run all demo queries. |
| 6 | Freeze code and dataset; finish documentation, report, slides, and a five-minute demo rehearsal. |
| 7 | Buffer for defects and setup problems; package and submit. |

## Acceptance checklist

- [ ] A fresh teammate can regenerate the cleaned data and Turtle file using the README.
- [ ] RDF parses without errors; entity URIs are unique and labels have `@vi` language tags.
- [ ] The report states article count, triple count, field coverage, linked-entity count, and manual link-review results.
- [ ] The endpoint loads the delivered dataset and executes at least three saved queries: entities by class, entities filtered by a domain field, and entities linked to English DBpedia.
- [ ] The demo traces one source article through the intermediate record, RDF triples, and SPARQL result.
- [ ] Limitations are explicit: narrow domain, partial field extraction, missing values, and links that could not be verified.

## Scope controls and contingencies

- If collection is slow, deliver **50 high-quality records** with a working end-to-end pipeline instead of a larger graph with broken mappings.
- If infobox extraction is inconsistent, keep the common fields (title, short description, source, type, English link) and only a few reliable domain properties.
- If a polished website would consume time, use Fuseki's built-in query interface or a terminal client. The brief requires an interface via endpoint/terminal, not a custom frontend.
- Never infer `owl:sameAs` from string similarity alone; omit uncertain links and report their count.

## Note on “4-star standard”

The brief's “4-star standard” likely refers to the linked-open-data model: use URI-identified resources and open RDF standards. External links to another dataset, such as English DBpedia, are commonly associated with the fifth star. Confirm the instructor's intended grading interpretation while implementing both RDF publication and verified links.

## References

- [W3C: 5 Star Linked Data](https://www.w3.org/2011/gld/wiki/5_Star_Linked_Data)
- [MediaWiki API: Language links](https://www.mediawiki.org/wiki/API:Langlinks)
- [DBpedia ontology](https://www.dbpedia.org/resources/ontology/)
- [DBpedia URI conventions](https://mappings.dbpedia.org/index.php/DBpedia_domains_and_URIs)
- [Apache Jena Fuseki quickstart](https://jena.apache.org/documentation/fuseki2/fuseki-quick-start.html)
