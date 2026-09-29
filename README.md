# Vietnamese DBpedia — Countries (Member 1: Data)

A reproducible, inspectable data pipeline for a HUST Master's Semantic Web
prototype. Vietnamese Wikipedia is the **factual source** for country records;
Wikidata is used only to find candidate pages and cross-check identity/sitelinks.
The output is handed to Member 2 for ontology/RDF work. An English DBpedia URI
here is a **link candidate**, not a confirmed identity link.

## Setup and checks

Install [uv](https://docs.astral.sh/uv/) and run from the repository root
(Python 3.12 is pinned in `.python-version`; no manual environment activation):

```sh
uv sync
uv run pytest
uv run pytest --cov=vi_dbpedia_data --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
```

## Pipeline and commands

Discovery → collection → **raw** API JSON → infobox inspection/extraction →
**interim** values and parse statuses → normalization → **processed** canonical
JSON/inspection CSV → validation → quality reports.

```sh
uv run vi-dbpedia-data reference                 # five fixed titles, small network run
uv run vi-dbpedia-data discover                  # candidate list, includes provenance
uv run vi-dbpedia-data collect --limit 20        # first 20 candidates; --force refreshes cache
uv run vi-dbpedia-data inspect                   # last collection selection
uv run vi-dbpedia-data inspect --reference-only  # cached reference set, even after another collect
uv run vi-dbpedia-data inspect --all             # all cached raw pages, across runs
uv run vi-dbpedia-data process
uv run vi-dbpedia-data validate
uv run vi-dbpedia-data report
uv run vi-dbpedia-data pilot                     # deterministic 20, including all five references
uv run vi-dbpedia-data full                      # explicit complete crawl only
uv run vi-dbpedia-data review-sample
uv run vi-dbpedia-data review-summary
```

`reference` uses **exactly** Việt Nam, Nhật Bản, Singapore, Nam Phi and Thụy Sĩ:
Unicode/diacritics, unlike English titles, city-state behavior, multiple capitals,
multiple official languages, and ambiguous/missing values. Its page IDs are indexed
in `data/reference/pages.json`. `pilot` includes these five plus 15 discovered
candidates selected from a stable sort with seed 42. Pilot first fetches the
five references to cross-check redirected titles/QIDs before sampling the other
15, avoiding the same known country twice. Individual failed collections
appear in the manifest and validation; the pipeline continues. `collect --limit`
uses candidate-file order, while `pilot` is sampled. `process` and default
`inspect` operate on the **most recent collection manifest**, not on unrelated
cached raw pages (`inspect --all` explicitly inspects all cached pages). Run
`collect` again before reprocessing a different selection. `--force` explicitly
refreshes raw pages; otherwise valid cached files are not overwritten.

### Data layers and hand-off

| Layer | Path | Contents |
| --- | --- | --- |
| Candidate | `data/candidates/countries.json`, `.csv` | QID, vi title/URL, English discovery *hint*, query provenance, optional Wikidata P31 type QIDs, deduplication conflicts |
| Raw | `data/raw/pages/<page_id>.json` | API extract and wikitext, final title/redirect, revision, pageprops QID, **vi Wikipedia English interlanguage link**, timestamp |
| Manifest | `data/raw/collection_manifest.csv` | Attempt/skip/failure per requested title, including collisions/redirects |
| Interim | `data/interim/extracted.jsonl` | Source infobox values, all source occurrences/colliding normalized keys, mapped raw values, field statuses/reasons/errors |
| Processed | `data/processed/countries.json`, `.csv` | Pydantic-validated canonical records; nested CSV cells contain JSON |
| Reports | `data/reports/` | Field status, source/value coverage, empty canonical values with reasons, parse errors, duplicates, link candidates, validation results, summary |

Canonical records contain `page_id` (int), `title_vi` (canonical title),
`abstract_vi` (plain-text intro or null), `source_url` (Vietnamese Wikipedia),
`revision_id` and `revision_timestamp` (nullable), `retrieved_at` (ISO-8601),
`wikidata_id` (pageprops QID or null), `english_title` (vi Wikipedia interlanguage
title or null), `english_wikipedia_url` and `english_dbpedia_candidate` (derived
URLs or null), `capital`, `currencies`, `official_languages` (lists of
`{ "label_vi": str, "wiki_title": str | null }`), `population_total` (int or
null), `area_km2` (float or null), and `calling_codes` (list of strings with `+`).
Missing scalars are `null`; missing lists are `[]`. No country facts are filled
from Wikidata. Numeric formats that cannot be interpreted safely stay missing
with an original raw value and a parse error in interim/reports.
`ResourceRef.label_vi` is the displayed Vietnamese label; `wiki_title` is the
Vietnamese Wikipedia link target where present and is the preferred identity
input for Member 2. `resource_ref_quality.csv` lists both values without
guessing a target when `wiki_title` is null. `summary.json` includes its total,
with-title/without-title counts and percentage.

Each infobox domain field in interim `parse_status` is **present** (normalized
value), **explicit_none** (source explicitly says none; canonical `[]`/`null`),
**source_missing** (no mapped parameter or only blank values), **parse_failed**
(a nonblank source cannot safely be parsed), or **ambiguous** (conflicting
nonblank values or multiple distinct top-level scalar numbers). `canonical_source_keys`,
`canonical_source_occurrences`, `field_provenance`, `field_reasons`, and
`normalized_key_collisions` retain the evidence. Repeated
normalized keys keep every original spelling/value; one nonblank value is
chosen only if all nonblank values agree. Source-driven explicit absence does
not itself trigger a validation warning. An empty canonical value is therefore
not necessarily an absent Wikipedia source parameter.

`data/reports/field_status.csv` gives one row for each of the six domain fields
per processed country. `field_coverage.csv` keeps its original
`available_count`/`missing_count`/`coverage_percentage` columns as **value**
coverage and adds `source_available_count`, `source_missing_count`,
`source_unknown_count`, `source_coverage_percentage` and
`explicit_none_count`. Source coverage counts any mapped Wikipedia parameter,
even a blank one; value coverage counts a nonempty canonical value. Metadata
fields have blank source-coverage cells because they do not come from a mapped
infobox parameter. `summary.json` includes both `source_field_coverage` and
`value_coverage`. `missing_values.csv` lists **empty canonical values** with
status/reason and source presence: `explicit_none` is not labeled source-missing.
`infobox_templates.csv` distinguishes `all_template_count` (all top-level
templates in the article) from `selected_infobox_parameter_count` (the chosen
country infobox's parameters). `normalized_key_collisions.csv` lists repeated
normalized infobox keys and their original source occurrences for inspection.
Numeric interpretation follows Vietnamese
grouping for three digits after a separator: `41.285` km² means 41,285 km²,
whereas `744.3` km² is decimal.

Inspect `data/reports/reference_infobox_keys.csv`,
`data/reports/infobox_templates.csv`, and
`data/reports/infobox_key_frequency.csv` after `reference` and `inspect`.
Update exact aliases in `config/country_mapping.yaml` based on actual keys and
rerun `process`, `validate`, `report`. Population selection is configured in
`source_priority`: a nonblank `population_estimate` wins; otherwise a nonblank
`population_census` is used; explicit generic total aliases are last. A blank
estimate does not block census; an ambiguous nonblank estimate is **not**
replaced with census. The chosen source type/key and its year parameter remain
in interim `field_provenance`, not in canonical JSON. A source
statement of *no official capital* or *no official language* stays an empty
list with `explicit_none` interim status. `recognised_national_languages` is
not used as a substitute for `official_languages`. Unknown keys stay in interim and
key frequency statistics. A directly mapped `official_languages` field always
has priority. Without one, `languages` is used only when `languages_type`
explicitly asserts official-language status (for example, “Ngôn ngữ chính thức”
or “Ngôn ngữ quốc gia (chính thức)”). Recognised, regional or merely national
languages are not promoted. The type/value source keys and mapping reason remain
in interim provenance.

`config/settings.yaml` controls API endpoints, polite network retry/backoff,
User-Agent (replace the example contact), reference titles, aliases for template
identification, sampling, and candidate-scoped `Infobox political division` fallback: only
raw pages collected as country candidates may use this alternative template;
having that template alone does not establish that a page is a country.
`infobox_templates.csv` records `candidate_template_alias` separately from
ordinary aliases, heuristics and `not_found`; the current-selection counts also
appear in `summary.json`.

The discovery query
first uses direct country/sovereign-state classes and, if fewer than 150 results
or the primary query fails, supplements via sovereign-state class hierarchy.
The candidate record keeps all query methods when discoveries overlap, and
reports QID/title conflicts; the title
is recanonicalized by the MediaWiki API and the authoritative English title is
collected from the **Vietnamese Wikipedia page**, never from the discovery hint.
Validation flags discrepancies with the Wikidata sitelink hint for review.
These semantic queries can include/exclude unexpected countries: inspect the
candidate list and collection manifest before a full run.

`candidate_audit.csv` lists every saved candidate's QID, vi/en sitlink hints,
discovery query/method, inclusion reason, saved `instance_qids` and review
flags. `candidate_summary.json` totals the candidates, query provenance,
instance types, missing type evidence and review reasons. The existing pilot's
candidate file was generated **before** instance QIDs were saved: its audit
marks exact P31 type as unknown instead of inferring one from the query. A
later user-run `discover` saves the P31 binding with each candidate for more
precise auditing. Q6256 (“country”) alone does not prove sovereign-state
status; broad classes, subclass-path candidates, title cues (e.g. regions or
realms) and conflicts are flagged for **human review**, not deleted or capped
at 200. Wikidata supplies no population, area, language, capital, currency or
phone-code facts in this pipeline.

### Manual link review

After processing at least 20 articles, `review-sample` creates 20 deterministic
rows in `data/reports/manual_link_review.csv` (seed 42). Fill `review_status`
with **correct**, **incorrect** or **uncertain**, and add `notes` as needed;
leave untouched rows blank. `review-summary` reports each count and observed
accuracy among definitively reviewed correct/incorrect rows; if there are none,
accuracy is `null`. Generating the sample again will not overwrite human edits.
The DBpedia URI is derived from the English interlanguage title, not checked
against DBpedia existence or approved as a semantic identity assertion.

### Reproducibility and limitations

`uv.lock`, configuration, reference index and small candidates/processed/reports
can be committed; large, redownloadable wikitext in `data/raw/pages/`, its
manifest, and generated interim JSONL are ignored. Regenerate them using
`reference`, or `discover` → `collect` (or `pilot` / explicit `full`), then
`inspect` → `process` → `validate` → `report`. Published processed data should
be regenerated after upstream edits; Wikipedia revisions can change over time,
so `revision_id` and `retrieved_at` capture what was actually retrieved.

Wikipedia infoboxes vary by template, aliases, language, and formatting; some
fields are absent or ambiguous (especially numerical text, templates and
units). The reference-informed mapping still requires refinement after
inspecting pilot keys. Some pages have no English link. Uncertain
templates/values remain inspectable, not inferred. The full list of current
sovereign states cannot be guaranteed by a single Wikidata class query; query
provenance and gaps should be reviewed manually. No RDF, ontology, SPARQL
service, or confirmed identity links are emitted by this repository.

### After local code changes

Run `uv sync`, `uv run pytest`, `uv run pytest --cov=vi_dbpedia_data
--cov-report=term-missing`, `uv run ruff check .` and
`uv run ruff format --check .`. To regenerate reports **without a request**
from the existing raw manifest, run `uv run vi-dbpedia-data inspect`, then
`uv run vi-dbpedia-data process`, `uv run vi-dbpedia-data validate` and
`uv run vi-dbpedia-data report`. When ready to fetch/refresh the deterministic
20-country dataset yourself, run `uv run vi-dbpedia-data pilot`, then inspect
the new reports and candidate audit before deciding on any full crawl.
