"""M2C.2: replay-verified, typed, synthetic stop derivation graph."""
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from math import ceil
import json

from . import ident, require, exact_tuple
from .identity import IdentityLedger
from .spatial import SpatialNetwork, Point, distance_m
from .evidence import PinnedSnapshot, FieldEvidence, StopAudit, audit_stops, _json


class Origin(Enum):
    ORIGINAL = "original"
    DERIVED = "derived"
    ESTIMATED = "estimated"


class Rule(Enum):
    STOP_DISTANCE_M_V1 = "stop_distance_m_v1"
    WALK_SECONDS_ESTIMATE_V1 = "walk_seconds_estimate_v1"
    SECONDS_TO_MINUTES_V1 = "seconds_to_minutes_v1"


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    rule: Rule
    subject: tuple[str, ...]
    parents: tuple[str, ...]
    value_json: str

    def __post_init__(self):
        ident(self.id)
        require(type(self.rule) is Rule, "unknown rule")
        exact_tuple(self.subject, str, "subject")
        require(len(self.subject) == 2 and self.subject[0] != self.subject[1],
                "ordered pair of distinct stop identities required")
        for x in self.subject: ident(x)
        exact_tuple(self.parents, str, "parents")
        for x in self.parents: ident(x)
        require(len(set(self.parents)) == len(self.parents), "duplicate parent")
        require(type(self.value_json) is str, "immutable JSON result required")


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    subject: tuple[str, ...]
    field: str
    value_json: str
    origin: Origin
    depends_on_estimate: bool
    parents: tuple[str, ...] = ()
    rule: Rule | None = None
    evidence: FieldEvidence | None = None


def _root_id(e: FieldEvidence) -> str:
    key = (e.key.namespace, e.key.kind.value, e.key.external_id,
           e.canonical_id, e.source_version, e.source_sha256, e.locator)
    return "syn:root-" + sha256(_json(key).encode("utf-8")).hexdigest()


def _roots(audit: StopAudit) -> tuple[Node, ...]:
    statuses = {(ext, f): status for ext, f, status in audit.rows}
    # Conservative field-level exclusion of observed alias/model disagreements.
    disputed = {(e.canonical_id, e.locator[-1]) for e in audit.evidence
                if statuses[(e.key.external_id, e.locator[-1])] == "model_mismatch"}
    return tuple(Node(_root_id(e), (e.canonical_id,), e.locator[-1],
                      e.value_json, Origin.ORIGINAL, False, evidence=e)
                 for e in audit.evidence
                 if statuses[(e.key.external_id, e.locator[-1])] == "present"
                 and (e.canonical_id, e.locator[-1]) not in disputed)


def _evaluate(rule: Rule, subject: tuple[str, ...], parents: tuple[Node, ...]):
    a, b = subject
    signature = tuple((n.subject, n.field) for n in parents)
    inherited = any(n.depends_on_estimate for n in parents)
    vals = tuple(json.loads(n.value_json) for n in parents)
    if rule is Rule.STOP_DISTANCE_M_V1:
        require(signature == (((a,), "latitude"), ((a,), "longitude"),
                              ((b,), "latitude"), ((b,), "longitude")),
                "coordinate parent signature mismatch")
        require(all(n.origin is Origin.ORIGINAL for n in parents), "original coordinates required")
        value = distance_m(Point(vals[0], vals[1]), Point(vals[2], vals[3]))
        return "great_circle_m", _json(value), Origin.DERIVED, inherited
    if rule is Rule.WALK_SECONDS_ESTIMATE_V1:
        require(signature == ((subject, "great_circle_m"),), "distance parent signature mismatch")
        # Illustrative policy only: direct great-circle distance / 1.2 m/s.
        return "illustrative_walk_seconds", _json(ceil(vals[0] / 1.2)), Origin.ESTIMATED, True
    if rule is Rule.SECONDS_TO_MINUTES_V1:
        require(signature == ((subject, "illustrative_walk_seconds"),), "time parent signature mismatch")
        return "illustrative_walk_minutes", _json(vals[0] / 60), Origin.DERIVED, inherited
    raise ValueError("unknown rule")


@dataclass(frozen=True, slots=True)
class DerivationGraph:
    spatial: SpatialNetwork
    ledger: IdentityLedger
    data: PinnedSnapshot
    scope: PinnedSnapshot
    claims: tuple[Claim, ...] = ()
    audit: StopAudit = field(init=False)
    nodes: tuple[Node, ...] = field(init=False)

    def __post_init__(self):
        exact_tuple(self.claims, Claim, "claims")
        audit = audit_stops(self.spatial, self.ledger, self.data, self.scope)
        roots = _roots(audit)
        known = {n.id: n for n in roots}
        require(len(known) == len(roots), "root ID collision")
        for c in self.claims:
            require(c.id not in known, "duplicate node ID")
            require(all(p in known for p in c.parents), "parent absent or not earlier in graph")
            f, value, origin, estimated = _evaluate(c.rule, c.subject,
                                                    tuple(known[p] for p in c.parents))
            require(c.value_json == value, "claimed result differs from recomputation")
            known[c.id] = Node(c.id, c.subject, f, value, origin, estimated, c.parents, c.rule)
        object.__setattr__(self, "audit", audit)
        object.__setattr__(self, "nodes", tuple(known.values()))

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise ValueError("unknown node")

    def original(self, stop_id: str, field_name: str) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.origin is Origin.ORIGINAL
                     and n.subject == (stop_id,) and n.field == field_name)

    def derive(self, node_id: str, rule: Rule, subject: tuple[str, ...],
               parents: tuple[str, ...]) -> "DerivationGraph":
        # Validate request shape before computation; then replay the whole graph.
        request = Claim(node_id, rule, subject, parents, "")
        _, value, _, _ = _evaluate(request.rule, request.subject,
                                   tuple(self.node(p) for p in request.parents))
        c = Claim(node_id, rule, subject, parents, value)
        return DerivationGraph(self.spatial, self.ledger, self.data, self.scope, self.claims + (c,))

    @property
    def publication_allowed(self): return False

    @property
    def source_authenticated(self): return False

    @property
    def scope_authority_verified(self): return False
