from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vi_dbpedia_data.models import CountryRecord, ResourceRef


def test_optional_fields_and_list_defaults_are_independent():
    data = {
        "page_id": 17,
        "title_vi": "Nhật Bản",
        "source_url": "https://vi.wikipedia.org/wiki/Nhật_Bản",
        "retrieved_at": datetime.now(UTC),
    }
    first = CountryRecord.model_validate(data)
    second = CountryRecord.model_validate({**data, "page_id": 18})
    first.capital.append(ResourceRef(label_vi="Tokyo", wiki_title="Tokyo"))
    assert second.capital == []
    assert second.population_total is None
    assert first.model_dump(mode="json")["retrieved_at"].endswith("Z")


def test_invalid_identity_and_resource():
    with pytest.raises(ValidationError):
        ResourceRef(label_vi="")
    with pytest.raises(ValidationError):
        CountryRecord(page_id=0, title_vi="X", source_url="x", retrieved_at=datetime.now(UTC))
