"""M2C.5A: persistent, checkpoint-bound replay of synthetic coverage audits.

The caller must retain the expected checkpoint outside the writable store.
No checkpoint authentication, trusted witness, or production authorization.
"""
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import sqlite3
from contextlib import closing

from . import (require, Agency, Stop, Route, Mode, Pattern, ServiceCalendar,
               ExceptionDay, Trip, Visit, Timing, ServiceTime, Network)
from .spatial import SpatialNetwork, Shape, Point, PatternGeometry, StationArea, Transfer
from .identity import IdentityLedger, Bind, Retire, SourceKey, EntityKind
from .coverage import canonical_records, audit_network
from .evidence import PinnedSnapshot, _json

FORMAT = "BOT-coverage-journal-v1"
GENESIS = sha256(FORMAT.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Checkpoint:
    count: int
    head: str

    def __post_init__(self):
        require(type(self.count) is int and self.count >= 0, "invalid checkpoint count")
        require(type(self.head) is str and re.fullmatch("[0-9a-f]{64}", self.head),
                "invalid checkpoint digest")
        require(self.count != 0 or self.head == GENESIS, "invalid genesis")


EMPTY = Checkpoint(0, GENESIS)


def _pack_snapshot(p):
    require(type(p) is PinnedSnapshot, "expected pinned artifact")
    return {"namespace":p.namespace, "version":p.version,
            "digest":p.expected_sha256, "bytes":p.payload.hex()}


def _unpack_snapshot(p):
    return PinnedSnapshot(p["namespace"], p["version"], p["digest"], bytes.fromhex(p["bytes"]))


def _events(ledger):
    return [["bind",e.key.namespace,e.key.kind.value,e.key.external_id,e.canonical_id,e.decision_ref]
            if type(e) is Bind else ["retire",e.kind.value,e.canonical_id,e.decision_ref]
            for e in ledger.events]


def _ledger(events):
    out=[]
    for e in events:
        if len(e)==6 and e[0]=="bind":
            out.append(Bind(SourceKey(e[1],EntityKind(e[2]),e[3]),e[4],e[5]))
        elif len(e)==4 and e[0]=="retire":
            out.append(Retire(EntityKind(e[1]),e[2],e[3]))
        else:
            raise ValueError("invalid identity event")
    return IdentityLedger(tuple(out))


def _model(spatial):
    return {"source_id":spatial.network.source_id,
            "anchor_policy":spatial.max_anchor_offset_m,"records":canonical_records(spatial)}


def _spatial(m):
    r=m["records"]
    def rows(kind): return sorted(r[kind].items())
    def time(t): return None if t is None else ServiceTime(t)
    n=Network(m["source_id"],
        tuple(Agency(i,**v) for i,v in rows("agency")),
        tuple(Stop(i,**v) for i,v in rows("stop")),
        tuple(Route(i,v["agency_id"],v["name"],Mode(v["mode"])) for i,v in rows("route")),
        tuple(Pattern(i,v["route_id"],v["direction"],tuple(v["stop_ids"])) for i,v in rows("pattern")),
        tuple(ServiceCalendar(i,date.fromisoformat(v["start"]),date.fromisoformat(v["end"]),
              tuple(v["weekdays"]),tuple(ExceptionDay(date.fromisoformat(d),b)
              for d,b in sorted(v["exceptions"].items()))) for i,v in rows("service")),
        tuple(Trip(i,v["pattern_id"],v["service_id"],tuple(
              Visit(x["stop_id"],time(x["arrival"]),time(x["departure"]),Timing(x["timing"]))
              for x in v["visits"])) for i,v in rows("trip")))
    return SpatialNetwork(n,
        tuple(Shape(i,tuple(Point(*p) for p in v["points"])) for i,v in rows("shape")),
        tuple(PatternGeometry(i,v["shape_id"],tuple(v["vertex_indices"])) for i,v in rows("geometry")),
        tuple(StationArea(i,v["name"],tuple(v["stop_ids"])) for i,v in rows("station")),
        tuple(Transfer(**v) for _,v in rows("transfer")),m["anchor_policy"])


def _report(report):
    return {**asdict(report),"relative_complete":report.relative_complete,
            "scoped_certificate":report.scoped_certificate,"publication_allowed":False,
            "scope_authority_verified":False,"source_authenticated":False}


def _record(spatial,ledger,snapshots,scope,reference):
    report=audit_network(spatial,ledger,snapshots,scope,reference)
    return {"format":FORMAT,"model":_model(spatial),"events":_events(ledger),
            "sources":[_pack_snapshot(s) for s in sorted(snapshots,key=lambda s:s.namespace)],
            "scope":_pack_snapshot(scope),"reference":_pack_snapshot(reference),
            "report":_report(report)}


def _replay(payload):
    obj=json.loads(payload)
    require(obj["format"]==FORMAT,"unsupported journal format")
    rebuilt=_record(_spatial(obj["model"]),_ledger(obj["events"]),
                    tuple(_unpack_snapshot(s) for s in obj["sources"]),
                    _unpack_snapshot(obj["scope"]),_unpack_snapshot(obj["reference"]))
    require(_json(rebuilt)==payload,"audit replay mismatch")
    return obj


def _hash(seq,prev,payload):
    return sha256(_json([FORMAT,seq,prev,payload]).encode()).hexdigest()


def _advance_history(obj, events, versions):
    new=obj["events"]
    require(new[:len(events)]==events,"identity history rewritten")
    for a in obj["sources"]+[obj["scope"],obj["reference"]]:
        key=(a["namespace"],a["version"])
        require(key not in versions or versions[key]==a["digest"],"source version equivocation")
        versions[key]=a["digest"]
    return new


def _scan(db):
    checkpoint=EMPTY
    events=[]
    versions={}
    reports=[]
    for seq,prev,payload,head in db.execute(
            "SELECT seq,prev,payload,head FROM audit_runs ORDER BY seq"):
        require(seq==checkpoint.count+1 and prev==checkpoint.head,"broken history sequence")
        require(type(payload) is str and head==_hash(seq,prev,payload),"broken history digest")
        obj=_replay(payload)
        events=_advance_history(obj,events,versions)
        reports.append(obj["report"])
        checkpoint=Checkpoint(seq,head)
    return checkpoint,events,versions,tuple(reports)


def initialize(path):
    """Exclusive initialization. Never implicitly recreate a missing store."""
    p=Path(path)
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(fd)
    with closing(sqlite3.connect(p)) as db, db:
        db.execute("CREATE TABLE audit_runs(seq INTEGER PRIMARY KEY,prev TEXT NOT NULL,"
                   "payload TEXT NOT NULL,head TEXT NOT NULL UNIQUE) STRICT")
        for action in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER reject_{action.lower()} BEFORE {action} ON audit_runs "
                       "BEGIN SELECT RAISE(ABORT,'append only'); END")
    return EMPTY


def _connect(path,mode):
    # URI mode rw/ro never creates a missing file.
    return sqlite3.connect(Path(path).resolve().as_uri()+"?mode="+mode,
                           uri=True,timeout=5,isolation_level=None)


def verify(path,expected):
    """Read-only full replay against an externally retained exact checkpoint."""
    require(type(expected) is Checkpoint,"external checkpoint required")
    with closing(_connect(path,"ro")) as db:
        db.execute("BEGIN")
        actual,_,_,reports=_scan(db)
        require(actual==expected,"external checkpoint mismatch")
        return reports


def append(path,expected,spatial,ledger,snapshots,scope,reference):
    """Compare-and-append under a single SQLite write transaction.

    Both successful and unsuccessful coverage reports are recorded.
    Return a proposed new checkpoint, not an independently witnessed one.
    """
    require(type(expected) is Checkpoint,"external checkpoint required")
    payload=_json(_record(spatial,ledger,snapshots,scope,reference))
    obj=_replay(payload)
    with closing(_connect(path,"rw")) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            actual,events,versions,_=_scan(db)
            require(actual==expected,"external checkpoint mismatch")
            _advance_history(obj,events,versions)
            seq=actual.count+1
            head=_hash(seq,actual.head,payload)
            db.execute("INSERT INTO audit_runs VALUES (?,?,?,?)",(seq,actual.head,payload,head))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return Checkpoint(seq,head)
