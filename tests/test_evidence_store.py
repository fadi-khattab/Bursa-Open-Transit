from concurrent.futures import ThreadPoolExecutor
import shutil
import sqlite3
import json
import pytest
from test_network_coverage import fixture, reference
from test_pinned_stop_evidence import pin
from bursa_transit.models.store import initialize, append, verify, EMPTY, Checkpoint, _hash
from bursa_transit.models.identity import Bind, SourceKey, EntityKind
from bursa_transit.models.evidence import _json


def inputs(version="v1",conflict=False):
    s,l,d,q=fixture()
    if conflict:
        l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"alias"),"syn:a","syn:alias"))
        d["records"]["stop"]["alias"]=dict(d["records"]["stop"]["0"],latitude=.001)
    d["version"]=q["version"]=version
    r=reference(l,(d,),q).document()
    r["version"]=version
    return s,l,(pin(d),),pin(q),pin(r)


def new(tmp_path):
    p=tmp_path/"audit.sqlite"
    assert initialize(p)==EMPTY
    return p


def test_reopen_replay(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    reports=verify(p,c)
    assert len(reports)==1 and reports[0]["scoped_certificate"]
    assert len(reports[0]["observations"])==32
    assert reports[0]["unknown_visits"]==[["syn:trip",1]]
    assert not reports[0]["publication_allowed"]


def test_conflict_history_retained(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs(conflict=True))
    s,l,ds,q,r=inputs("v2")
    l=inputs(conflict=True)[1]  # retain prior identity history
    d=ds[0].document()
    ref=reference(l,(d,),q.document()).document()
    ref["version"]="v2"
    c2=append(p,c,s,l,ds,q,pin(ref))
    a,b=verify(p,c2)
    assert a["conflicts"]==[["stop","syn:a","latitude"]]
    assert not a["scoped_certificate"] and b["scoped_certificate"]


def test_rollback_and_missing_store(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    backup=tmp_path/"old.sqlite"
    shutil.copyfile(p,backup)
    c2=append(p,c,*inputs("v2"))
    shutil.copyfile(backup,p)
    with pytest.raises(ValueError,match="checkpoint"): verify(p,c2)
    with pytest.raises(ValueError,match="checkpoint"): append(p,c2,*inputs("v2"))
    p.unlink()
    with pytest.raises(sqlite3.OperationalError): append(p,c2,*inputs("v2"))
    assert not p.exists()


def test_exclusive_initialization(tmp_path):
    p=new(tmp_path)
    with pytest.raises(FileExistsError): initialize(p)
    assert verify(p,EMPTY)==()


@pytest.mark.parametrize("action",["UPDATE audit_runs SET head='x'","DELETE FROM audit_runs"])
def test_normal_sql_mutation_rejected(tmp_path,action):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    with sqlite3.connect(p) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(action)
    assert len(verify(p,c))==1


def test_direct_rewrite_and_rehash_cannot_match_checkpoint(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    other=tmp_path/"alternative.sqlite"
    initialize(other)
    alternate=append(other,EMPTY,*inputs(conflict=True))
    assert c!=alternate
    shutil.copyfile(other,p)
    with pytest.raises(ValueError,match="checkpoint"): verify(p,c)
    assert len(verify(p,alternate))==1  # externally supplied trust remains essential


def test_rehash_fabricated_report_fails_replay(tmp_path):
    p=new(tmp_path)
    append(p,EMPTY,*inputs())
    with sqlite3.connect(p) as db:
        seq,prev,payload,head=db.execute("SELECT * FROM audit_runs").fetchone()
        o=json.loads(payload);o["report"]["observations"]=[]
        payload=_json(o);head=_hash(seq,prev,payload)
        db.execute("DROP TRIGGER reject_update")
        db.execute("UPDATE audit_runs SET payload=?,head=?",(payload,head))
    with pytest.raises(ValueError,match="replay"): verify(p,Checkpoint(1,head))


def test_stale_writer_and_concurrency(tmp_path):
    p=new(tmp_path)
    def writer(i):
        try: return append(p,EMPTY,*inputs("v"+str(i)))
        except ValueError as e:
            assert "checkpoint" in str(e)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(writer,(1,2)))
    winners=[r for r in results if r is not None]
    assert len(winners)==1 and len(verify(p,winners[0]))==1


def test_same_version_changed_bytes_rejected_atomically(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    with pytest.raises(ValueError,match="equivocation"):
        append(p,c,*inputs(conflict=True))
    assert len(verify(p,c))==1


def test_identity_history_cannot_shrink(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs(conflict=True))
    with pytest.raises(ValueError,match="history rewritten"):
        append(p,c,*inputs("v2"))
    assert len(verify(p,c))==1


def test_unwitnessed_append_not_accepted_as_current(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    with pytest.raises(ValueError,match="checkpoint"):verify(p,EMPTY)
    assert len(verify(p,c))==1


def test_independent_digest_oracle(tmp_path):
    from hashlib import sha256
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    c=append(p,c,*inputs("v2"))
    # Separate oracle: do not import the store's hash or replay helpers.
    tag="BOT-coverage-journal-v1"
    head=sha256(tag.encode()).hexdigest()
    with sqlite3.connect(p) as db:
        for i,(seq,prev,payload,stored) in enumerate(db.execute(
                "SELECT seq,prev,payload,head FROM audit_runs ORDER BY seq"),1):
            assert seq==i and prev==head
            data=json.dumps([tag,i,head,payload],sort_keys=True,separators=(",",":"),
                            ensure_ascii=False,allow_nan=False).encode()
            head=sha256(data).hexdigest()
            assert head==stored
            obj=json.loads(payload)
            for a in obj["sources"]+[obj["scope"],obj["reference"]]:
                assert sha256(bytes.fromhex(a["bytes"])).hexdigest()==a["digest"]
    assert c.count==2 and c.head==head


def test_sql_insert_failure_leaves_checkpoint_unchanged(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    with sqlite3.connect(p) as db:
        db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON audit_runs "
                   "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError,match="injected"):
        append(p,c,*inputs("v2"))
    assert len(verify(p,c))==1


def test_stale_checkpoint_after_successful_append(tmp_path):
    p=new(tmp_path)
    c=append(p,EMPTY,*inputs())
    with pytest.raises(ValueError,match="checkpoint"):
        append(p,EMPTY,*inputs("v2"))
    assert len(verify(p,c))==1
