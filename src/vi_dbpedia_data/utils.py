"""Configuration, files, HTTP retry policy, and link URI encoding."""

import csv
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import yaml
from pydantic import BaseModel, Field

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    wikidata_sparql_url: str
    wikipedia_api_url: str
    user_agent: str
    request_timeout: float = Field(gt=0)
    retry_count: int = Field(ge=0)
    retry_backoff: float = Field(ge=0)
    polite_delay: float = Field(ge=0)
    batch_size: int = Field(gt=0, le=20)
    pilot_seed: int
    pilot_size: int = Field(gt=0)
    reference_titles: list[str]
    infobox_template_aliases: list[str]
    candidate_infobox_template_aliases: list[str] = Field(default_factory=list)


def load_settings(root: Path = ROOT) -> Settings:
    return Settings.model_validate(
        yaml.safe_load((root / "config/settings.yaml").read_text("utf-8"))
    )


def load_mapping(root: Path = ROOT) -> dict[str, dict]:
    mapping = yaml.safe_load((root / "config/country_mapping.yaml").read_text("utf-8"))
    seen: dict[str, str] = {}
    for field, spec in mapping.items():
        if spec["type"] not in {"resource_list", "integer", "area_km2", "string_list"}:
            raise ValueError(f"Unsupported mapping type for {field}: {spec['type']}")
        for alias in spec["aliases"]:
            key = normalize_key(alias)
            if key in seen and seen[key] != field:
                raise ValueError(f"Alias {alias!r} belongs to both {seen[key]} and {field}")
            seen[key] = field
        if "source_priority" in spec:
            configured = {normalize_key(alias) for alias in spec["aliases"]}
            grouped = [
                normalize_key(alias)
                for group in spec["source_priority"]
                for alias in group["aliases"]
            ]
            if set(grouped) != configured or len(grouped) != len(set(grouped)):
                raise ValueError(f"source_priority aliases must partition {field} aliases")
        fallback = spec.get("contextual_fallback")
        if fallback and fallback["required_semantics"] != "official":
            raise ValueError(f"Unsupported contextual semantics for {field}")
    return mapping


def normalize_key(value: str) -> str:
    import unicodedata

    return re.sub(
        r"\s+", "_", unicodedata.normalize("NFC", value).strip().casefold().replace("_", " ")
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", "utf-8"
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def article_url(title: str, *, lang: str = "vi", dbpedia: bool = False) -> str:
    """Encode a MediaWiki article title, without encoding the path separators."""
    title = title.strip().replace(" ", "_")
    if dbpedia:
        return f"http://dbpedia.org/resource/{quote(title, safe='()_-')}"
    if lang not in {"vi", "en"}:
        raise ValueError(f"Unexpected Wikipedia language: {lang}")
    return f"https://{lang}.wikipedia.org/wiki/{quote(title, safe='()_-')}"


def is_vi_wikipedia_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname == "vi.wikipedia.org"


class HttpClient:
    """One shared, polite, retrying session for both upstream APIs."""

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})

    def get_json(self, url: str, params: dict) -> dict:
        for attempt in range(self.settings.retry_count + 1):
            try:
                if self.settings.polite_delay:
                    time.sleep(self.settings.polite_delay)
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                result = response.json()
                if "error" in result:
                    raise ValueError(f"API error from {url}: {result['error']}")
                return result
            except (requests.RequestException, ValueError) as exc:
                # Do not retry malformed data, authentication failures or other 4xx.
                retryable = isinstance(exc, requests.ConnectionError | requests.Timeout)
                if isinstance(exc, requests.HTTPError):
                    retryable = exc.response is not None and exc.response.status_code in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                if not retryable or attempt == self.settings.retry_count:
                    raise RuntimeError(f"Request failed for {url}: {exc}") from exc
                LOG.warning("Retrying %s after %s (attempt %d)", url, exc, attempt + 1)
                time.sleep(self.settings.retry_backoff * (2**attempt))
        raise AssertionError("unreachable")
