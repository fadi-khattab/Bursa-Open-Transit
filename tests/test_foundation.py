import json
from pathlib import Path
import pytest

from bursa_transit import __version__
from bursa_transit.__main__ import main
from bursa_transit.publishing import publication_decision
from bursa_transit.sources import load_synthetic_fixture

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/synthetic/metadata.json"

def test_version():
    assert __version__ == "0.1.0.dev1"

def test_bundled_synthetic_fixture():
    assert load_synthetic_fixture(FIXTURE).source_id == "bot-synthetic-v1"

@pytest.mark.parametrize("classification", ["authorized", "real", "unverified", "", None])
def test_other_classifications_rejected(tmp_path, classification):
    data = json.loads(FIXTURE.read_text())
    data["classification"] = classification
    p = tmp_path / "invalid.json"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_synthetic_fixture(p)

@pytest.mark.parametrize("data", [[], {}, {"classification": "synthetic"}, {"classification":"synthetic","source_id":"other","description":"other"}])
def test_invalid_schema_or_identity_rejected(tmp_path, data):
    p = tmp_path / "invalid.json"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_synthetic_fixture(p)

def test_malformed_json_rejected(tmp_path):
    p = tmp_path / "invalid.json"
    p.write_text("{")
    with pytest.raises(ValueError):
        load_synthetic_fixture(p)

def test_release_denied():
    decision = publication_decision()
    assert decision.allowed is False
    assert "not implemented" in decision.reason

def test_cli_status(capsys):
    main()
    status = json.loads(capsys.readouterr().out)
    assert status["mode"] == "development-only"
    assert status["real_data_ingestion"] is False
    assert status["publication_allowed"] is False
