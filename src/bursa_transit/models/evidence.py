"""M2C.1: pinned source bytes, typed stop identity and scoped coverage.

Offline synthetic slice only. Pins are caller-supplied expected digests;
they establish byte consistency, not source authenticity or authorization.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from math import isfinite

from . import ident, name, require
from .identity import EntityKind, IdentityLedger, SourceKey
from .spatial import SpatialNetwork


def _unique_object(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "duplicate JSON key")
        result[k] = v
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _finite_float(value):
    number = float(value)
    require(isfinite(number), "nonfinite JSON number")
    return number


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True, slots=True)
class PinnedSnapshot:
    namespace: str
    version: str
    expected_sha256: str
    payload: bytes

    def __post_init__(self):
        ident(self.namespace)
        name(self.version)
        require(type(self.expected_sha256) is str and
                re.fullmatch(r"[0-9a-f]{64}", self.expected_sha256) is not None,
                "invalid expected digest")
        require(type(self.payload) is bytes, "immutable source bytes required")
        self.document()

    def document(self):
        require(sha256(self.payload).hexdigest() == self.expected_sha256,
                "source digest mismatch")
        obj = json.loads(self.payload.decode("utf-8"),
                         object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant,
                         parse_float=_finite_float)
        require(type(obj) is dict, "source document must be object")
        require(obj.get("namespace") == self.namespace and
                obj.get("version") == self.version, "source metadata mismatch")
        return obj


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    key: SourceKey
    canonical_id: str
    source_version: str
    source_sha256: str
    locator: tuple[str, ...]
    value_json: str


@dataclass(frozen=True, slots=True)
class StopAudit:
    rows: tuple[tuple[str, str, str], ...]
    evidence: tuple[FieldEvidence, ...]
    unexpected_source_ids: tuple[str, ...]
    missing_model_ids: tuple[str, ...]
    unexpected_model_ids: tuple[str, ...]
    data_sha256: str
    scope_sha256: str

    @property
    def relative_complete(self):
        return (bool(self.rows) and all(s == "present" for _, _, s in self.rows)
                and not self.unexpected_source_ids and not self.missing_model_ids
                and not self.unexpected_model_ids)

    @property
    def source_authenticated(self): return False

    @property
    def scope_authority_verified(self): return False

    @property
    def publication_allowed(self): return False


def _valid_field(field, value):
    if field == "name":
        return type(value) is str and bool(value.strip())
    bound = 90 if field == "latitude" else 180
    return type(value) in (int, float) and -bound <= value <= bound and isfinite(value)


def audit_stops(spatial: SpatialNetwork, ledger: IdentityLedger,
                data: PinnedSnapshot, scope: PinnedSnapshot) -> StopAudit:
    """Audit exactly one selected stop snapshot against an explicit inventory.

    No fallback name/coordinate matching; no derived values; no claim that
    two different files or namespaces are institutionally independent.
    """
    require(type(spatial) is SpatialNetwork, "SpatialNetwork required")
    require(type(ledger) is IdentityLedger, "IdentityLedger required")
    require(type(data) is PinnedSnapshot and type(scope) is PinnedSnapshot,
            "pinned data and scope required")
    require(data.namespace != scope.namespace and
            data.expected_sha256 != scope.expected_sha256,
            "separate declared scope artifact required")
    observed = data.document()
    expected = scope.document()
    require(set(observed) == {"namespace", "version", "stops"},
            "invalid stop source envelope")
    require(set(expected) == {"namespace", "version", "data_namespace",
                              "data_version", "stops"}, "invalid scope envelope")
    require(expected["data_namespace"] == data.namespace and
            expected["data_version"] == data.version, "scope targets different snapshot")
    records, inventory = observed["stops"], expected["stops"]
    require(type(records) is dict and type(inventory) is dict and bool(inventory),
            "nonempty expected stop inventory required")
    keys = {}
    for ext, cid in inventory.items():
        keys[ext] = SourceKey(data.namespace, EntityKind.STOP, ext)
        ident(cid)
    for ext in records:
        SourceKey(data.namespace, EntityKind.STOP, ext)
    stops = {s.id: s for s in spatial.network.stops}
    expected_ids = set(inventory.values())
    rows, evidence = [], []
    for ext in sorted(inventory):
        cid, key = inventory[ext], keys[ext]
        if ledger.resolve(key) != cid:
            rows.append((ext, "identity", "unresolved_or_conflicting"))
            continue
        rows.append((ext, "identity", "present"))
        if ext not in records:
            rows.append((ext, "record", "missing"))
            continue
        record = records[ext]
        if type(record) is not dict:
            rows.append((ext, "record", "invalid"))
            continue
        if cid not in stops:
            rows.append((ext, "model", "missing"))
            continue
        for field in ("name", "latitude", "longitude"):
            if field not in record:
                rows.append((ext, field, "missing"))
                continue
            value = record[field]
            if not _valid_field(field, value):
                rows.append((ext, field, "invalid"))
                continue
            evidence.append(FieldEvidence(key, cid, data.version, data.expected_sha256,
                                          ("stops", ext, field), _json(value)))
            # Coordinate comparison uses exact numeric equality, not fuzzy matching.
            status = "present" if value == getattr(stops[cid], field) else "model_mismatch"
            rows.append((ext, field, status))
    return StopAudit(tuple(rows), tuple(evidence),
                     tuple(sorted(set(records) - set(inventory))),
                     tuple(sorted(expected_ids - set(stops))),
                     tuple(sorted(set(stops) - expected_ids)),
                     data.expected_sha256, scope.expected_sha256)
