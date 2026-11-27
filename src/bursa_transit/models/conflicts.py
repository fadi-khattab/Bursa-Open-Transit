"""M2C.3: replay-verified alternatives and scoped conflict isolation.

A candidate is usable in the selected hypothetical evidence scenario,
not authenticated truth. No quarantine decision is authorized by this module.
"""
from dataclasses import dataclass, field
from enum import Enum
import json

from . import exact_tuple, ident, require
from .identity import IdentityLedger
from .spatial import SpatialNetwork
from .evidence import PinnedSnapshot, StopAudit, audit_stops
from .derivation import Claim, Node, Origin, Rule, _root_id, _evaluate


class Status(Enum):
    CANDIDATE = "candidate"
    DISPUTED = "disputed"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class Selection:
    data: PinnedSnapshot
    scope: PinnedSnapshot

    def __post_init__(self):
        require(type(self.data) is PinnedSnapshot and type(self.scope) is PinnedSnapshot,
                "pinned artifacts required")


@dataclass(frozen=True, slots=True)
class Scenario:
    """Caller-selected exclusions; no claim of fault attribution or authority."""
    proof_ids: tuple[str, ...] = ()
    artifact_digests: tuple[str, ...] = ()

    def __post_init__(self):
        for values in (self.proof_ids, self.artifact_digests):
            exact_tuple(values, str, "exclusion list")
            require(len(set(values)) == len(values), "duplicate exclusion")
        for value in self.proof_ids:
            ident(value)


@dataclass(frozen=True, slots=True)
class Proof:
    id: str
    node: Node | None
    status: Status
    reason: str
    roots: tuple[str, ...]
    artifacts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Conclusion:
    subject: tuple[str, ...]
    field: str
    status: Status
    alternatives: tuple[str, ...]
    value_json: str | None
    # A non-estimated alternative is not a proof of world accuracy.
    has_nonestimated_candidate: bool


_LEVEL = {Rule.STOP_DISTANCE_M_V1: 1, Rule.WALK_SECONDS_ESTIMATE_V1: 2,
          Rule.SECONDS_TO_MINUTES_V1: 3}


def _value_key(n: Node):
    # All current fields are validated scalar strings or finite numbers.
    # Exact Python numeric equality is intentional (e.g. 0 == 0.0).
    value = json.loads(n.value_json)
    return ("text", value) if type(value) is str else ("number", value)


@dataclass(frozen=True, slots=True)
class ConflictGraph:
    spatial: SpatialNetwork
    ledger: IdentityLedger
    selections: tuple[Selection, ...]
    claims: tuple[Claim, ...] = ()
    scenario: Scenario = Scenario()
    audits: tuple[StopAudit, ...] = field(init=False)
    proofs: tuple[Proof, ...] = field(init=False)
    conclusions: tuple[Conclusion, ...] = field(init=False)

    def __post_init__(self):
        exact_tuple(self.selections, Selection, "selections")
        exact_tuple(self.claims, Claim, "claims")
        require(bool(self.selections), "empty selections")
        require(type(self.scenario) is Scenario, "scenario required")
        namespaces = [s.data.namespace for s in self.selections]
        require(len(set(namespaces)) == len(namespaces), "one selected version per data namespace")
        all_artifacts = {p.expected_sha256 for s in self.selections for p in (s.data, s.scope)}
        require(set(self.scenario.artifact_digests) <= all_artifacts, "unknown excluded artifact")
        audits = tuple(audit_stops(self.spatial, self.ledger, s.data, s.scope)
                       for s in self.selections)
        nodes, levels, roots, artifacts, invalid = {}, {}, {}, {}, {}
        # Keep model-disagreeing, valid extracted values as evidence candidates.
        # Scope membership, typed identity resolution and model membership are
        # still prerequisites inherited from audit_stops.
        for s, audit in zip(self.selections, audits):
            for e in audit.evidence:
                nid = _root_id(e)
                require(nid not in nodes, "root collision")
                nodes[nid] = Node(nid, (e.canonical_id,), e.locator[-1], e.value_json,
                                  Origin.ORIGINAL, False, evidence=e)
                levels[nid] = 0
                roots[nid] = (nid,)
                artifacts[nid] = tuple(sorted({e.source_sha256, s.scope.expected_sha256}))
        ids = tuple(c.id for c in self.claims)
        require(len(set(ids)) == len(ids) and not set(ids).intersection(nodes),
                "duplicate proof ID")
        require(set(self.scenario.proof_ids) <= (set(nodes) | set(ids)),
                "unknown excluded proof")
        for c in self.claims:
            try:
                require(all(p in nodes for p in c.parents), "parent absent, invalid or not earlier")
                level = _LEVEL[c.rule]
                require(all(levels[p] < level for p in c.parents), "invalid dependency level")
                f, value, origin, estimated = _evaluate(c.rule, c.subject,
                                                       tuple(nodes[p] for p in c.parents))
                require(value == c.value_json, "claimed result differs from recomputation")
            except ValueError as exc:
                invalid[c.id] = Proof(c.id, None, Status.INVALID, str(exc), (), ())
                continue
            nodes[c.id] = Node(c.id, c.subject, f, value, origin, estimated, c.parents, c.rule)
            levels[c.id] = level
            roots[c.id] = tuple(sorted({r for p in c.parents for r in roots[p]}))
            artifacts[c.id] = tuple(sorted({a for p in c.parents for a in artifacts[p]}))

        excluded = set(self.scenario.proof_ids)
        excluded_artifacts = set(self.scenario.artifact_digests)
        result = dict(invalid)
        groups = {}
        for level in range(4):
            live = {}
            for nid, n in nodes.items():
                if levels[nid] != level:
                    continue
                key = (n.subject, n.field)
                groups.setdefault(key, []).append(nid)
                if nid in excluded or (level == 0 and excluded_artifacts.intersection(artifacts[nid])):
                    status, reason = Status.QUARANTINED, "explicit scenario exclusion"
                elif any(result[p].status is not Status.CANDIDATE for p in n.parents):
                    status, reason = Status.BLOCKED, "noncandidate parent"
                else:
                    status, reason = Status.CANDIDATE, "replayed within selected scenario"
                    live.setdefault(key, []).append(nid)
                result[nid] = Proof(nid, n, status, reason, roots[nid], artifacts[nid])
            for members in live.values():
                if len({_value_key(nodes[nid]) for nid in members}) > 1:
                    for nid in members:
                        result[nid] = Proof(nid, nodes[nid], Status.DISPUTED,
                                            "incompatible live values", roots[nid], artifacts[nid])
        conclusions = []
        for (subject, f), members in sorted(groups.items()):
            active = tuple(sorted(nid for nid in members if result[nid].status is Status.CANDIDATE))
            disputed = any(result[nid].status is Status.DISPUTED for nid in members)
            status = Status.DISPUTED if disputed else Status.CANDIDATE if active else Status.BLOCKED
            # Keep every proof in alternatives, including blocked and quarantined proofs.
            value = nodes[active[0]].value_json if active else None
            conclusions.append(Conclusion(subject, f, status, tuple(sorted(members)), value,
                                          any(not nodes[nid].depends_on_estimate for nid in active)))
        object.__setattr__(self, "audits", audits)
        object.__setattr__(self, "proofs", tuple(result[nid] for nid in sorted(result)))
        object.__setattr__(self, "conclusions", tuple(conclusions))

    def proof(self, nid):
        for p in self.proofs:
            if p.id == nid:
                return p
        raise ValueError("unknown proof")

    def conclusion(self, subject, field_name):
        for c in self.conclusions:
            if (c.subject, c.field) == (subject, field_name):
                return c
        return None

    @property
    def source_authenticated(self): return False

    @property
    def scope_authority_verified(self): return False

    @property
    def publication_allowed(self): return False
