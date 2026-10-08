# Capstone Project Report
**Project Title:** Build a DBpedia Version for the Vietnamese Language
**Domain Scope:** Countries and Sovereign States

---

## 1. Executive Summary

This project successfully constructs a Vietnamese-language equivalent of DBpedia for the domain of countries. By systematically scraping and processing semi-structured Vietnamese Wikipedia infoboxes, the project has generated a Semantic Web-compliant, 5-star Linked Open Data (LOD) Knowledge Graph. The final dataset encompasses 197 countries, modeled using the standard DBpedia ontology, linked to the global English DBpedia dataset, and hosted on a locally deployable SPARQL endpoint using Apache Jena Fuseki.

## 2. Introduction

### 2.1. Background
DBpedia is a crowd-sourced community effort to extract structured information from Wikipedia and make it available on the Semantic Web. While the English DBpedia is incredibly comprehensive, localized versions are crucial for cross-lingual NLP, regional knowledge graphs, and localized semantic search.

### 2.2. Project Objectives
As per the official capstone brief, this project set out to achieve five core objectives:
1. **Define an ontology** representing the collected information and its relationships.
2. **Collect Vietnamese Wikipedia articles** as the primary data source.
3. **Transform the data into the 4-star standard** (using W3C standards like RDF).
4. **Establish links to English DBpedia** to interconnect the Vietnamese dataset with the global LOD cloud.
5. **Provide a query interface** to allow users to interact with the semantic data.

## 3. System Architecture and Design

The system is designed as an end-to-end data pipeline, split into a Python-based extraction/transformation toolset and a Dockerized hosting environment.

### 3.1. Data Collection Pipeline (Web Scraping)
The data extraction is orchestrated via a bespoke CLI tool (`vi-dbpedia-data`). It queries the Wikidata API to discover all existing entities classified as countries, subsequently mapping them to their localized Vietnamese Wikipedia counterparts. The raw Wikitext is then extracted using the MediaWiki API.

### 3.2. Ontology and Schema Design
Following Linked Open Data best practices, the project avoided inventing redundant vocabularies and instead aggressively reused the **DBpedia Ontology (`dbo:`)** and W3C standard vocabularies (`rdfs:`, `owl:`, `foaf:`).

*   **Namespace (`ex:`):** `http://vi.dbpedia.org/resource/` is used for all canonical entities (e.g., `ex:Việt_Nam`).
*   **Properties:** Mapped standard demographic data to strictly-typed RDF properties.
    *   `title_vi` → `rdfs:label` (Literal with `@vi` language tag)
    *   `population_total` → `dbo:populationTotal` (Typed as `xsd:integer`)
    *   `area_km2` → `dbo:areaTotal` (Typed as `xsd:double`)
    *   `capital` → `dbo:capital` (Object property linking to a new URI, e.g., `ex:Hà_Nội`)

## 4. Implementation and Fulfillment of Requirements

### 4.1. Transforming to the 4-Star Standard (Req 3)
To achieve the 4-star Linked Data classification, data must be structured in a non-proprietary format using open W3C standards like RDF.
*   **Implementation:** The Python `rdflib` library is used to transform the cleaned JSON extracts into a directed RDF graph. The data is serialized into the **Turtle (`.ttl`)** format, outputting strictly typed literals and well-formed URIs rather than strings. 

### 4.2. Establishing Links to English DBpedia (Req 4)
Fulfilling this requirement officially pushes the dataset into the **5-Star Open Data** tier, as it provides context by linking to other people's data.
*   **Implementation:** The pipeline cross-references the Vietnamese article's underlying Wikidata QID with the English DBpedia database. When an exact structural match is found, the script generates an `owl:sameAs` triple (e.g., `ex:Việt_Nam owl:sameAs <http://dbpedia.org/resource/Vietnam>`). This asserts strict logical equivalence between the regional node and the global node.

### 4.3. Providing a Query Interface (Req 5)
*   **Implementation:** A `docker-compose.yml` file is provided to orchestrate an instance of **Apache Jena Fuseki** (`stain/jena-fuseki:latest`). The finalized `countries.ttl` file is mounted into the container as a read-only volume. This provides a robust, industry-standard SPARQL endpoint at `http://localhost:3030/vi-dbpedia`, complete with a web GUI for end-users to execute relational graph queries.

## 5. Project Structure

The repository is modularly structured to separate the pipeline logic from the generated artifacts:

```text
vn-dpedia-country/
├── src/vi_dbpedia_data/       # Python source code for the extraction pipeline
│   ├── cli.py                 # Command Line Interface routing
│   ├── collect.py             # MediaWiki API fetching
│   ├── extract.py             # Wikitext to JSON parser
│   └── rdf.py                 # JSON to RDF/Turtle Transformer (rdflib)
├── data/
│   ├── raw/                   # Raw downloaded Wikipedia wikitext files
│   ├── processed/             # Cleaned JSON infobox data
│   ├── rdf/                   # Final output: countries.ttl (The Semantic Graph)
│   └── queries/               # Sample SPARQL queries for evaluation
├── docs/                      # Extensive documentation (Ontology, Pipeline setup)
├── pyproject.toml             # Modern Python dependency management (uv)
└── docker-compose.yml         # Container configuration for Apache Jena Fuseki
```

## 6. Achievements and Results

1.  **High-Fidelity Extraction:** Successfully harvested and processed 197 sovereign state records from Vietnamese Wikipedia.
2.  **Semantic Graph Generation:** Synthesized a dense, highly connected RDF graph containing exactly **2,796 triples**.
3.  **Cross-Lingual Identity:** Established robust interlanguage links (`owl:sameAs`) for nearly all entries, allowing queries to easily traverse between the Vietnamese dataset and the English DBpedia dataset.
4.  **Operational Web Service:** Deployed a fully functional SPARQL endpoint that can instantaneously process complex mathematical, string, and relational graph queries (e.g., "Find all countries using the Euro with a population over 10 million").

## 7. Conclusion

This capstone project successfully demonstrates the entire lifecycle of Semantic Web data engineering. By bridging the gap between semi-structured regional Wikitext and a formalized, 5-star Linked Open Data graph, the project fulfills all mandated requirements. The resulting localized DBpedia slice serves as a foundational prototype that can be readily scaled horizontally to encompass broader domains (e.g., Cities, People, Organizations) in the Vietnamese language space.

