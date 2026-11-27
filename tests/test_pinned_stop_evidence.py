from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
import pytest

from bursa_transit.models.demo import build_demo
from bursa_transit.models.spatial import SpatialNetwork
from bursa_transit.models.identity import Bind, Retire, EntityKind, IdentityLedger, SourceKey
from bursa_transit.models.evidence import PinnedSnapshot, audit_stops
from bursa_transit.publishing import publication_decision


def pin(doc):
    payload = json.dumps(doc, sort_keys=True).encode()
    return PinnedSnapshot(doc["namespace"], doc["version"], sha256(payload).hexdigest(), payload)


def fixture():
    spatial = SpatialNetwork(build_demo())
    records = {str(i): {"name": s.name, "latitude": s.latitude, "longitude": s.longitude}
               for i, s in enumerate(spatial.network.stops)}
    inventory = {str(i): s.id for i, s in enumerate(spatial.network.stops)}
    data = {"namespace": "syn:data", "version": "v1", "stops": records}
    scope = {"namespace": "syn:scope", "version": "v1", "data_namespace": "syn:data",
             "data_version": "v1", "stops": inventory}
    ledger = IdentityLedger(tuple(Bind(SourceKey("syn:data", EntityKind.STOP, ext), cid,
                                        "syn:decision-"+ext) for ext, cid in inventory.items()))
    return spatial, ledger, data, scope


def run(spatial, ledger, data, scope):
    return audit_stops(spatial, ledger, pin(data), pin(scope))


def test_verified_original_fields_bound_to_spatial_model():
    r = run(*fixture())
    assert r.relative_complete and len(r.evidence) == 9
    assert all(e.source_sha256 == r.data_sha256 and e.key.kind is EntityKind.STOP for e in r.evidence)
    assert r.evidence[0].locator == ("stops", "0", "name")
    assert r.evidence[0].value_json == '"Fictional A"'
    assert not r.publication_allowed and not r.source_authenticated and not r.scope_authority_verified
    assert not publication_decision().allowed
    with pytest.raises(FrozenInstanceError): r.rows = ()


def test_digest_mismatch():
    _, _, d, _ = fixture()
    p = pin(d)
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(p, payload=p.payload+b" ")


def test_metadata_mismatch():
    _, _, d, _ = fixture()
    with pytest.raises(ValueError, match="metadata mismatch"):
        replace(pin(d), version="v2")


@pytest.mark.parametrize("body", [
    b'{"namespace":"syn:data","version":"v1","stops":{"0":1,"0":2}}',
    b'{"namespace":"syn:data","version":"v1","stops":{"0":NaN}}',
])
def test_ambiguous_json(body):
    with pytest.raises(ValueError):
        PinnedSnapshot("syn:data","v1",sha256(body).hexdigest(),body)


def test_missing_expected_record():
    s,l,d,q = fixture()
    del d["stops"]["1"]
    r = run(s,l,d,q)
    assert ("1","record","missing") in r.rows and not r.relative_complete


def test_missing_field():
    s,l,d,q = fixture()
    del d["stops"]["0"]["latitude"]
    r = run(s,l,d,q)
    assert ("0","latitude","missing") in r.rows and not r.relative_complete


@pytest.mark.parametrize("field,value", [("latitude", True), ("longitude",181),("name"," "),("latitude",None)])
def test_invalid_field(field,value):
    s,l,d,q = fixture()
    d["stops"]["0"][field] = value
    r = run(s,l,d,q)
    assert ("0",field,"invalid") in r.rows and not r.relative_complete


def test_fabricated_model_value_does_not_pass():
    s,l,d,q = fixture()
    d["stops"]["0"]["name"] = "Unmatched name"
    r = run(s,l,d,q)
    assert ("0","name","model_mismatch") in r.rows and not r.relative_complete


def test_pinned_bytes_not_proof_of_truth():
    s,l,d,q = fixture()
    assert run(s,l,d,q).relative_complete
    assert not run(s,l,d,q).source_authenticated


def test_unbound_and_retired_identity():
    s,l,d,q = fixture()
    r = run(s,IdentityLedger(),d,q)
    assert ("0","identity","unresolved_or_conflicting") in r.rows and not r.relative_complete
    l = l.append(Retire(EntityKind.STOP,"syn:a","syn:retirement"))
    assert not run(s,l,d,q).relative_complete


def test_wrong_kind_does_not_resolve():
    s,l,d,q = fixture()
    events = tuple(Bind(SourceKey(e.key.namespace,EntityKind.ROUTE,e.key.external_id),
                        e.canonical_id,e.decision_ref) for e in l.events)
    assert not run(s,IdentityLedger(events),d,q).relative_complete


def test_wrong_canonical_binding():
    s,l,d,q = fixture()
    q["stops"]["0"] = "syn:b"
    assert not run(s,l,d,q).relative_complete


def test_scope_cannot_ignore_model_stop():
    s,l,d,q = fixture()
    del d["stops"]["1"]
    del q["stops"]["1"]
    r = run(s,l,d,q)
    assert r.unexpected_model_ids == ("syn:b",) and not r.relative_complete


def test_unexpected_source_stop():
    s,l,d,q = fixture()
    d["stops"]["extra"] = d["stops"]["0"].copy()
    r = run(s,l,d,q)
    assert r.unexpected_source_ids == ("extra",) and not r.relative_complete


def test_scope_missing_model_stop():
    s,l,d,q = fixture()
    q["stops"]["9"] = "syn:absent"
    r = run(s,l,d,q)
    assert r.missing_model_ids == ("syn:absent",) and not r.relative_complete


def test_empty_scope_rejected():
    s,l,d,q = fixture()
    q["stops"] = {}
    with pytest.raises(ValueError,match="nonempty"):
        run(s,l,d,q)


def test_scope_wrong_version():
    s,l,d,q = fixture()
    q["data_version"] = "v2"
    with pytest.raises(ValueError,match="different snapshot"):
        run(s,l,d,q)


def test_scope_same_namespace_rejected():
    s,l,d,q = fixture()
    q["namespace"] = d["namespace"]
    with pytest.raises(ValueError,match="separate"):
        run(s,l,d,q)


def test_alias_must_agree_with_canonical_value():
    s,l,d,q = fixture()
    q["stops"]["alias"]="syn:a"
    d["stops"]["alias"]=d["stops"]["0"].copy()
    l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"alias"),"syn:a","syn:alias-decision"))
    assert run(s,l,d,q).relative_complete
    d["stops"]["alias"]["name"]="Conflicting"
    assert not run(s,l,d,q).relative_complete

def test_overflowing_json_number_rejected():
    body=b'{"namespace":"syn:data","version":"v1","stops":{"0":1e999}}'
    with pytest.raises(ValueError,match="nonfinite"):
        PinnedSnapshot("syn:data","v1",sha256(body).hexdigest(),body)


def test_literal_reference_fixture_not_derived_from_model():
    s,l,_,_=fixture()
    data={"namespace":"syn:data","version":"v1","stops":{
        "0":{"name":"Fictional A","latitude":0,"longitude":0},
        "1":{"name":"Fictional B","latitude":0,"longitude":0.01},
        "2":{"name":"Fictional C","latitude":0.01,"longitude":0.01}}}
    scope={"namespace":"syn:scope","version":"v1","data_namespace":"syn:data",
           "data_version":"v1","stops":{"0":"syn:a","1":"syn:b","2":"syn:c"}}
    assert run(s,l,data,scope).relative_complete
    from dataclasses import replace
    n=s.network
    changed=replace(n,stops=(replace(n.stops[0],name="Fabricated"),)+n.stops[1:])
    assert not run(replace(s,network=changed),l,data,scope).relative_complete
