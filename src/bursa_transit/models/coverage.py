"""M2C.4: exhaustive observation scan and reference-relative network coverage.

Normalized synthetic source contract; no raw agency adapter or authority.
"""
from dataclasses import dataclass
from hashlib import sha256
from . import ident, require, exact_tuple, Timing
from .evidence import PinnedSnapshot, _json
from .identity import EntityKind, IdentityLedger, SourceKey, Bind
from .spatial import SpatialNetwork

KINDS = tuple(k.value for k in EntityKind)
FIELDS = {
    "agency": ("name", "timezone"),
    "stop": ("name", "latitude", "longitude"),
    "route": ("agency_id", "name", "mode"),
    "pattern": ("route_id", "direction", "stop_ids"),
    "service": ("start", "end", "weekdays", "exceptions"),
    "trip": ("pattern_id", "service_id", "visits"),
    "shape": ("points",),
    "station": ("name", "stop_ids"),
    "geometry": ("shape_id", "vertex_indices"),
    "transfer": ("from_stop", "to_stop", "minimum_seconds"),
}

def digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()

def ledger_digest(ledger):
    require(type(ledger) is IdentityLedger, "IdentityLedger required")
    return digest([["bind", e.key.namespace, e.key.kind.value, e.key.external_id,
                    e.canonical_id, e.decision_ref] if type(e) is Bind
                   else ["retire", e.kind.value, e.canonical_id, e.decision_ref]
                   for e in ledger.events])

def transfer_id(a, b):
    return "syn:transfer-" + digest([a, b])

def canonical_records(spatial):
    """Explicit serialization of every current transit entity and nested occurrence."""
    require(type(spatial) is SpatialNetwork, "SpatialNetwork required")
    n = spatial.network
    return {
        "agency": {x.id: {"name": x.name, "timezone": x.timezone} for x in n.agencies},
        "stop": {x.id: {"name": x.name, "latitude": x.latitude, "longitude": x.longitude}
                 for x in n.stops},
        "route": {x.id: {"agency_id": x.agency_id, "name": x.name, "mode": x.mode.value}
                  for x in n.routes},
        "pattern": {x.id: {"route_id": x.route_id, "direction": x.direction,
                            "stop_ids": list(x.stop_ids)} for x in n.patterns},
        "service": {x.id: {"start": x.start.isoformat(), "end": x.end.isoformat(),
                            "weekdays": sorted(x.weekdays),
                            "exceptions": {e.date.isoformat(): e.operates for e in x.exceptions}}
                    for x in n.calendars},
        "trip": {x.id: {"pattern_id": x.pattern_id, "service_id": x.service_id,
                         "visits": [{"stop_id": v.stop_id,
                                     "arrival": None if v.arrival is None else v.arrival.seconds,
                                     "departure": None if v.departure is None else v.departure.seconds,
                                     "timing": v.timing.value} for v in x.visits]}
                 for x in n.trips},
        "shape": {x.id: {"points": [[p.latitude, p.longitude] for p in x.points]}
                  for x in spatial.shapes},
        "station": {x.id: {"name": x.name, "stop_ids": sorted(x.stop_ids)}
                    for x in spatial.areas},
        "geometry": {x.pattern_id: {"shape_id": x.shape_id,
                                    "vertex_indices": list(x.vertex_indices)}
                     for x in spatial.geometry},
        "transfer": {transfer_id(x.from_stop, x.to_stop): {
            "from_stop": x.from_stop, "to_stop": x.to_stop,
            "minimum_seconds": x.minimum_seconds} for x in spatial.transfers},
    }

@dataclass(frozen=True, slots=True)
class Observation:
    namespace: str
    version: str
    source_sha256: str
    kind: str
    external_id: str
    canonical_id: str
    field: str
    value_json: str

    @property
    def locator(self):
        return ("records", self.kind, self.external_id, self.field)

@dataclass(frozen=True, slots=True)
class CoverageReport:
    observations: tuple[Observation, ...]
    issues: tuple[tuple[str, ...], ...]
    conflicts: tuple[tuple[str, str, str], ...]
    reference_matches: bool
    reference_sha256: str
    scope_sha256: str
    sources: tuple[tuple[str, str], ...]
    ledger_sha256: str
    model_sha256: str
    unknown_visits: tuple[tuple[str, int], ...]
    estimated_visits: tuple[tuple[str, int], ...]

    @property
    def relative_complete(self):
        return not self.issues

    @property
    def scoped_certificate(self):
        return self.reference_matches and self.relative_complete and not self.conflicts

    @property
    def scope_authority_verified(self): return False

    @property
    def source_authenticated(self): return False

    @property
    def publication_allowed(self): return False


def _groups(obj):
    require(type(obj) is dict and set(obj) == set(KINDS),
            "all entity groups must be explicitly present, including empty groups")
    require(all(type(v) is dict for v in obj.values()), "entity groups must be objects")
    return obj

def audit_network(spatial, ledger, snapshots, scope, reference):
    """Recompute report; never accept a caller-supplied report or exclusion scenario."""
    require(type(ledger) is IdentityLedger, "IdentityLedger required")
    exact_tuple(snapshots, PinnedSnapshot, "snapshots")
    require(bool(snapshots), "nonempty source set required")
    require(type(scope) is PinnedSnapshot and type(reference) is PinnedSnapshot,
            "pinned scope and reference required")
    namespaces = {s.namespace for s in snapshots}
    require(len(namespaces) == len(snapshots), "one selected version per source")
    require(len(namespaces | {scope.namespace, reference.namespace}) == len(namespaces)+2,
            "separate declared namespaces required")
    q, r = scope.document(), reference.document()
    require(set(q) == {"namespace", "version", "inventory"}, "invalid scope envelope")
    require(set(r) == {"namespace", "version", "scope_sha256", "sources", "ledger_sha256"},
            "invalid reference envelope")
    require(type(q["inventory"]) is dict and bool(q["inventory"]), "empty scope")
    expected = q["inventory"]
    for ns, groups in expected.items():
        ident(ns)
        for kind, entries in _groups(groups).items():
            for ext, cid in entries.items():
                SourceKey(ns, EntityKind(kind), ext)
                ident(cid)
    require(any(entries for groups in expected.values() for entries in groups.values()),
            "empty expected inventory")
    source_pins = tuple(sorted((s.namespace, s.expected_sha256) for s in snapshots))
    ld = ledger_digest(ledger)
    ref_ok = (r["scope_sha256"] == scope.expected_sha256 and
              r["sources"] == dict(source_pins) and r["ledger_sha256"] == ld)
    model = canonical_records(spatial)
    expected_keys = {(kind,cid) for groups in expected.values()
                     for kind, entries in groups.items() for cid in entries.values()}
    model_keys = {(kind,cid) for kind, entries in model.items() for cid in entries}
    issues, observations = [], []
    for ns in sorted(set(expected)-namespaces): issues.append(("missing_source", ns))
    for ns in sorted(namespaces-set(expected)): issues.append(("unexpected_source", ns))
    for kind,cid in sorted(expected_keys-model_keys): issues.append(("missing_model",kind,cid))
    for kind,cid in sorted(model_keys-expected_keys): issues.append(("unexpected_model",kind,cid))
    for s in sorted(snapshots,key=lambda x:x.namespace):
        doc = s.document()
        require(set(doc) == {"namespace", "version", "records"}, "invalid source envelope")
        groups = _groups(doc["records"])
        wanted = expected.get(s.namespace, {kind:{} for kind in KINDS})
        for kind, entries in sorted(groups.items()):
            inv = wanted[kind]
            for ext in sorted(set(inv)-set(entries)):
                issues.append(("missing_record",s.namespace,kind,ext))
            # Crucial: iterate observed records, not the scope inventory.
            for ext, record in sorted(entries.items()):
                key = SourceKey(s.namespace, EntityKind(kind), ext)
                cid = ledger.resolve(key)
                loc = (s.namespace,kind,ext)
                if ext not in inv: issues.append(("unexpected_record",*loc))
                elif inv[ext] != cid: issues.append(("identity_mismatch",*loc))
                if cid is None:
                    issues.append(("unresolved_identity",*loc))
                    continue
                canonical = model[kind].get(cid)
                if canonical is None: issues.append(("unrepresented_identity",*loc))
                if type(record) is not dict:
                    issues.append(("invalid_record",*loc))
                    continue
                for field in sorted(set(FIELDS[kind])-set(record)):
                    issues.append(("missing_field",*loc,field))
                for field in sorted(set(record)-set(FIELDS[kind])):
                    issues.append(("unexpected_field",*loc,field))
                for field in sorted(set(record)&set(FIELDS[kind])):
                    value = _json(record[field])
                    observations.append(Observation(s.namespace,s.version,s.expected_sha256,
                                                    kind,ext,cid,field,value))
                    if canonical is not None and value != _json(canonical[field]):
                        issues.append(("model_mismatch",*loc,field))
    values = {}
    for o in observations:
        values.setdefault((o.kind,o.canonical_id,o.field),set()).add(o.value_json)
    conflicts = tuple(sorted(k for k,v in values.items() if len(v)>1))
    unknown = tuple(sorted((t.id,i) for t in spatial.network.trips
                           for i,v in enumerate(t.visits) if v.timing is Timing.UNKNOWN))
    estimates = tuple(sorted((t.id,i) for t in spatial.network.trips
                             for i,v in enumerate(t.visits) if v.timing is Timing.ESTIMATED))
    return CoverageReport(tuple(observations),tuple(sorted(issues)),conflicts,ref_ok,
                          reference.expected_sha256,scope.expected_sha256,source_pins,ld,
                          digest({"source_id":spatial.network.source_id,"records":model,
                                  "anchor_policy":spatial.max_anchor_offset_m}),unknown,estimates)
