# Vietnamese DBpedia Prototype: Project Documentation

This project is a reproducible, inspectable data pipeline for a Semantic Web capstone prototype. It crawls Vietnamese Wikipedia for country records, cleans the data, transforms it into an RDF knowledge graph modeled after the DBpedia ontology, and provides a SPARQL endpoint for querying.

## 1. Project Structure

The repository is structured to separate raw data, intermediate processing, generated graphs, and source code cleanly.

```text
vn-dpedia-country/
├── src/vi_dbpedia_data/     # Core Python source code
│   ├── cli.py               # CLI command orchestrator
│   ├── discover.py          # Wikidata candidate discovery
│   ├── collect.py           # MediaWiki API retrieval
│   ├── extract.py           # Infobox extraction and normalization
│   ├── rdf.py               # RDF graph generation
│   └── ...                  # Utilities, reports, validation models
├── data/
│   ├── candidates/          # Discovered candidate lists and scope decisions
│   ├── raw/                 # Raw JSON API dumps from Wikipedia
│   ├── interim/             # Extracted values before normalization
│   ├── processed/           # Cleaned canonical JSON/CSV records
│   ├── rdf/                 # Generated Turtle (.ttl) knowledge graph
│   ├── queries/             # Sample SPARQL queries (.rq)
│   └── reports/             # Validation results and coverage summaries
├── config/                  # Pipeline configurations (scope rules, aliases)
├── tests/                   # Pytest suite
├── docs/                    # Project descriptions and plans
├── docker-compose.yml       # Apache Jena Fuseki local query service
├── pyproject.toml           # Python dependencies and build system
└── uv.lock                  # Locked dependency tree
```

## 2. Installation Guide

### Prerequisites
- **Python 3.12+**
- **uv**: A fast Python package manager.
- **Docker & Docker Compose**: Required to run the local SPARQL query service.

### Setup Instructions
1. **Install uv** (if not already installed):
   - **Windows (PowerShell)**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - **macOS/Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Clone the repository and sync dependencies**:
   ```sh
   # Navigate to the project root
   cd vn-dpedia-country
   
   # Sync virtual environment and install dependencies (including rdflib)
   uv sync
   ```
3. **Verify Installation**:
   ```sh
   uv run pytest
   ```

## 3. Data Crawling Guide

The crawling pipeline operates in several auditable stages. Vietnamese Wikipedia is the factual source; Wikidata is only used to discover candidates and cross-check identities.

### Standard End-to-End Run
To run the explicit complete crawl:
```sh
uv run vi-dbpedia-data full
```
This single command automatically discovers candidates, calculates scope, collects the approved subset, inspects infoboxes, processes the data, and runs validation reports.

### Step-by-Step Crawling
If you wish to run the pipeline manually or debug intermediate steps:

1. **Discover Candidates**: Queries Wikidata for entities classified as sovereign states.
   ```sh
   uv run vi-dbpedia-data discover
   ```
2. **Calculate Scope**: Filters the discovered list down to approved countries based on `config/scope_policy.yaml`.
   ```sh
   uv run vi-dbpedia-data scope
   ```
3. **Collect Raw Pages**: Fetches the raw JSON content and English interlanguage links from the MediaWiki API.
   ```sh
   uv run vi-dbpedia-data collect
   ```
4. **Extract and Process**: Parses the raw wikitext, normalizes the infobox fields, and produces `data/processed/countries.json`.
   ```sh
   uv run vi-dbpedia-data inspect
   uv run vi-dbpedia-data process
   ```
5. **Validate and Report**: Checks for anomalies and generates coverage summaries in `data/reports/`.
   ```sh
   uv run vi-dbpedia-data validate
   uv run vi-dbpedia-data report
   ```

## 4. Ontology and RDF Generation

Once the data is cleaned and processed, it must be mapped to the DBpedia ontology (e.g., `dbo:Country`, `dbo:capital`, `dbo:populationTotal`) and serialized to a standard Linked Open Data format.

**Generate the RDF Knowledge Graph:**
```sh
uv run vi-dbpedia-data rdf
```
This command reads the processed `countries.json` and outputs an RDF Turtle file to `data/rdf/countries.ttl`.

- **Namespace**: Entities are hosted under `http://vi.dbpedia.org/resource/`
- **Ontology**: Attributes use standard properties from `http://dbpedia.org/ontology/`
- **External Links**: Approved candidates feature `owl:sameAs` links to English DBpedia.

## 5. Query Service Run Guide

To satisfy the 4-star standard and provide an interface to interact with the knowledge graph, an Apache Jena Fuseki SPARQL endpoint is pre-configured.

1. **Start the Query Service**:
   Ensure Docker Desktop is running, then execute:
   ```sh
   docker-compose up -d
   ```
   *(The Fuseki container will automatically load `data/rdf/countries.ttl` on startup).*

2. **Access the Interface**:
   Open a web browser and navigate to **[http://localhost:3030](http://localhost:3030)**.

3. **Run Sample Queries**:
   Click on the `/vi-dbpedia` dataset, go to the "Query" tab, and try out the sample SPARQL queries located in `data/queries/sample_queries.rq`. Examples include:
   - Listing all countries and their capitals.
   - Filtering for countries with a population over 50 million.
   - Finding cross-lingual links mapping Vietnamese entities to English DBpedia.

4. **Shutdown Service**:
   ```sh
   docker-compose down
   ```
