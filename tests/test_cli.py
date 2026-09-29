from vi_dbpedia_data import cli
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.utils import ROOT, write_json


def test_pilot_orchestration_avoids_reference_redirect_duplicate(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.yaml").write_text(
        (ROOT / "config/settings.yaml").read_text("utf-8"), encoding="utf-8"
    )
    candidates = [
        CandidateCountry(title_vi="Cộng hòa Nam Phi", wikidata_id="Q258", discovery_method="test")
    ]
    candidates += [
        CandidateCountry(title_vi=f"Nước {index}", wikidata_id=f"Q{index}", discovery_method="test")
        for index in range(100, 125)
    ]
    calls = []

    def fake_reference(_settings, root):
        calls.append("reference")
        write_json(root / "data/raw/pages/2.json", {"pageprops_wikidata_id": "Q258"})
        return [
            {
                "requested_title": "Nam Phi",
                "raw_file_path": "data/raw/pages/2.json",
                "collection_status": "collected",
            }
        ]

    def fake_collect(selected, _settings, _root):
        calls.append("collect")
        assert len(selected) == 20
        assert selected[3].title_vi == "Nam Phi"
        assert all(item.title_vi != "Cộng hòa Nam Phi" for item in selected[5:])
        return [{"collection_status": "collected"} for _ in selected]

    monkeypatch.setattr(cli, "discover", lambda *_: candidates)
    monkeypatch.setattr(cli, "collect_reference", fake_reference)
    monkeypatch.setattr(cli, "collect", fake_collect)
    monkeypatch.setattr(cli, "_finish", lambda _: calls.append("finish"))
    assert cli.main(["--root", str(tmp_path), "pilot"]) == 0
    assert calls == ["reference", "collect", "finish"]
