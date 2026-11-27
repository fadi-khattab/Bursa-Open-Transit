"""M2B: explicit synthetic identity decisions, replayable without guessing."""
from dataclasses import dataclass
from enum import Enum
from . import ident, name, require, exact_tuple

class EntityKind(Enum):
    AGENCY="agency"
    STOP="stop"
    ROUTE="route"
    PATTERN="pattern"
    TRIP="trip"
    SERVICE="service"
    SHAPE="shape"
    STATION="station"
    GEOMETRY="geometry"
    TRANSFER="transfer"

@dataclass(frozen=True, slots=True)
class SourceKey:
    namespace: str
    kind: EntityKind
    external_id: str

    def __post_init__(self):
        ident(self.namespace)
        require(type(self.kind) is EntityKind,"invalid entity kind")
        name(self.external_id)
        require(all(c.isprintable() and not c.isspace() for c in self.external_id),
                "invalid external ID")

@dataclass(frozen=True, slots=True)
class Bind:
    key: SourceKey
    canonical_id: str
    decision_ref: str

    def __post_init__(self):
        require(type(self.key) is SourceKey,"invalid source key")
        ident(self.canonical_id)
        ident(self.decision_ref)

@dataclass(frozen=True, slots=True)
class Retire:
    kind: EntityKind
    canonical_id: str
    decision_ref: str

    def __post_init__(self):
        require(type(self.kind) is EntityKind,"invalid entity kind")
        ident(self.canonical_id)
        ident(self.decision_ref)

@dataclass(frozen=True, slots=True)
class IdentityLedger:
    """Pure event history. Not an authenticated, concurrent or durable authority."""
    events: tuple[Bind | Retire,...] = ()

    def __post_init__(self):
        require(type(self.events) is tuple and all(type(e) in (Bind,Retire) for e in self.events),
                "invalid identity event history")
        self._state()

    def _state(self):
        bindings={}
        retired=set()
        issued=set()
        for e in self.events:
            if type(e) is Bind:
                target=(e.key.kind,e.canonical_id)
                require(target not in retired,"retired identity cannot be bound")
                require(e.key not in bindings,"source key already bound; no rebinding or reuse")
                bindings[e.key]=e.canonical_id
                issued.add(target)
            else:
                target=(e.kind,e.canonical_id)
                require(target in issued and target not in retired,"unknown or retired identity")
                retired.add(target)
        return bindings,retired

    def append(self, event: Bind | Retire) -> "IdentityLedger":
        return IdentityLedger(self.events+(event,))

    def resolve(self,key: SourceKey) -> str | None:
        require(type(key) is SourceKey,"invalid source key")
        bindings,retired=self._state()
        value=bindings.get(key)
        return None if (key.kind,value) in retired else value

    def historical_id(self,key: SourceKey) -> str | None:
        require(type(key) is SourceKey,"invalid source key")
        return self._state()[0].get(key)

    def resolve_snapshot(self,keys: tuple[SourceKey,...]) -> tuple[str | None,...]:
        exact_tuple(keys,SourceKey,"snapshot keys")
        # Absence never implies retirement. Unknown identity never auto-matches.
        bindings,retired=self._state()
        return tuple(None if (k.kind,bindings.get(k)) in retired else bindings.get(k) for k in keys)
