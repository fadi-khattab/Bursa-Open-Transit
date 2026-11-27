"""Offline synthetic source handling only."""
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SyntheticFixture:
    source_id: str
    description: str

def load_synthetic_fixture(path: Path) -> SyntheticFixture:
    # Classification is a format check, not a grant of authority.
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"classification", "source_id", "description"}:
        raise ValueError("Invalid development fixture schema")
    if data["classification"] != "synthetic":
        raise ValueError("Only synthetic development fixtures are supported")
    if data["source_id"] != "bot-synthetic-v1" or data["description"] != "Fictional test metadata; not passenger information.":
        raise ValueError("Unrecognized synthetic fixture")
    return SyntheticFixture(data["source_id"], data["description"])
