"""Typed interchange formats for the three data layers and review results."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DOMAIN_FIELDS = (
    "capital",
    "population_total",
    "area_km2",
    "currencies",
    "official_languages",
    "calling_codes",
)


class ResourceRef(BaseModel):
    label_vi: str = Field(min_length=1)
    wiki_title: str | None = None


class CandidateCountry(BaseModel):
    wikidata_id: str | None = None
    title_vi: str = Field(min_length=1)
    wikipedia_url: str | None = None
    english_title_hint: str | None = None
    discovery_method: str
    discovery_methods: list[str] = Field(default_factory=list)
    discovery_conflicts: list[str] = Field(default_factory=list)
    instance_qids: list[str] = Field(default_factory=list)


class RawPage(BaseModel):
    candidate_wikidata_id: str | None = None
    requested_title: str = Field(min_length=1)
    page_id: int = Field(gt=0)
    canonical_title: str = Field(min_length=1)
    redirects: list[dict[str, str]] = Field(default_factory=list)
    source_url: str
    extract: str | None = None
    wikitext: str = Field(min_length=1)
    revision_id: int | None = None
    revision_timestamp: str | None = None
    pageprops_wikidata_id: str | None = None
    langlinks: dict[str, str] = Field(default_factory=dict)
    retrieved_at: datetime


class CountryRecord(BaseModel):
    page_id: int = Field(gt=0)
    title_vi: str = Field(min_length=1)
    abstract_vi: str | None = None
    source_url: str
    revision_id: int | None = None
    revision_timestamp: str | None = None
    retrieved_at: datetime
    wikidata_id: str | None = None
    english_title: str | None = None
    english_wikipedia_url: str | None = None
    english_dbpedia_candidate: str | None = None
    capital: list[ResourceRef] = Field(default_factory=list)
    population_total: int | None = None
    area_km2: float | None = None
    currencies: list[ResourceRef] = Field(default_factory=list)
    official_languages: list[ResourceRef] = Field(default_factory=list)
    calling_codes: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    page_id: int | None
    title_vi: str
    status: Literal["valid", "warning", "invalid"]
    reasons: list[str] = Field(default_factory=list)
