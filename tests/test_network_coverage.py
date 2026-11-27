from dataclasses import replace
from copy import deepcopy
import pytest
from test_pinned_stop_evidence import pin
from bursa_transit.models.demo import build_demo
from bursa_transit.models.spatial import SpatialNetwork, Point, Shape, PatternGeometry, StationArea, Transfer
from bursa_transit.models.identity import EntityKind, SourceKey, Bind, Retire, IdentityLedger
from bursa_transit.models.coverage import audit_network, canonical_records, ledger_digest, transfer_id, KINDS
from bursa_transit.publishing import publication_decision

def fixture():
    s=SpatialNetwork(build_demo(),shapes=(Shape("syn:shape",(Point(0.0,0.0),Point(0.0,.01),
        Point(.01,.01),Point(0.0,0.0))),),geometry=(PatternGeometry("syn:pattern","syn:shape",(0,1,2,3)),),
        areas=(StationArea("syn:station","Fictional area",("syn:a","syn:b")),),
        transfers=(Transfer("syn:a","syn:b",45),))
    # Literal source fixture, independent of the serializer under test.
    records={
        "agency":{"syn:agency":{"name":"Fictional operator","timezone":"Europe/Istanbul"}},
        "stop":{"syn:a":{"name":"Fictional A","latitude":0.0,"longitude":0.0},
                "syn:b":{"name":"Fictional B","latitude":0.0,"longitude":.01},
                "syn:c":{"name":"Fictional C","latitude":.01,"longitude":.01}},
        "route":{"syn:route":{"agency_id":"syn:agency","name":"Fictional loop","mode":"bus"}},
        "pattern":{"syn:pattern":{"route_id":"syn:route","direction":"loop",
                   "stop_ids":["syn:a","syn:b","syn:c","syn:a"]}},
        "service":{"syn:weekday":{"start":"2026-11-01","end":"2026-12-31","weekdays":[1,2,3,4,5],
                   "exceptions":{"2026-11-27":False,"2026-11-28":True}}},
        "trip":{"syn:trip":{"pattern_id":"syn:pattern","service_id":"syn:weekday","visits":[
            {"stop_id":"syn:a","arrival":86100,"departure":86100,"timing":"known"},
            {"stop_id":"syn:b","arrival":None,"departure":None,"timing":"unknown"},
            {"stop_id":"syn:c","arrival":86880,"departure":86940,"timing":"estimated"},
            {"stop_id":"syn:a","arrival":87600,"departure":87600,"timing":"known"}]}},
        "shape":{"syn:shape":{"points":[[0.0,0.0],[0.0,.01],[.01,.01],[0.0,0.0]]}},
        "station":{"syn:station":{"name":"Fictional area","stop_ids":["syn:a","syn:b"]}},
        "geometry":{"syn:pattern":{"shape_id":"syn:shape","vertex_indices":[0,1,2,3]}},
        "transfer":{transfer_id("syn:a","syn:b"):{"from_stop":"syn:a","to_stop":"syn:b","minimum_seconds":45}},
    }
    inventory={k:{str(i):cid for i,cid in enumerate(sorted(rs))} for k,rs in records.items()}
    ledger=IdentityLedger(tuple(Bind(SourceKey("syn:data",EntityKind(k),ext),cid,"syn:decision")
                               for k,rs in inventory.items() for ext,cid in rs.items()))
    data={"namespace":"syn:data","version":"v1","records":{
        k:{ext:records[k][cid] for ext,cid in inv.items()} for k,inv in inventory.items()}}
    scope={"namespace":"syn:scope","version":"v1","inventory":{"syn:data":inventory}}
    return s,ledger,data,scope

def reference(l, docs, q):
    return pin({"namespace":"syn:reference","version":"v1","scope_sha256":pin(q).expected_sha256,
                "sources":{d["namespace"]:pin(d).expected_sha256 for d in docs},
                "ledger_sha256":ledger_digest(l)})

def run(s,l,d,q,r=None):
    docs=d if type(d) is tuple else (d,)
    return audit_network(s,l,tuple(pin(x) for x in docs),pin(q),r or reference(l,docs,q))

def test_literal_complete_all_kinds_but_not_authorized():
    s,l,d,q=fixture()
    r=run(s,l,d,q)
    assert r.relative_complete and r.scoped_certificate and r.reference_matches
    assert set(o.kind for o in r.observations)==set(KINDS)
    assert len(r.observations)==32
    assert r.unknown_visits==(("syn:trip",1),) and r.estimated_visits==(("syn:trip",2),)
    assert not r.publication_allowed and not r.source_authenticated and not r.scope_authority_verified
    assert not publication_decision().allowed
    assert all(o.source_sha256==pin(d).expected_sha256 for o in r.observations)

@pytest.mark.parametrize("kind",KINDS)
def test_missing_record_each_kind(kind):
    s,l,d,q=fixture()
    d["records"][kind].pop(next(iter(d["records"][kind])))
    r=run(s,l,d,q)
    assert not r.scoped_certificate and any(i[0]=="missing_record" and i[2]==kind for i in r.issues)

@pytest.mark.parametrize("kind",KINDS)
def test_missing_field_each_kind(kind):
    s,l,d,q=fixture()
    row=next(iter(d["records"][kind].values()))
    row.pop(next(iter(row)))
    r=run(s,l,d,q)
    assert not r.scoped_certificate and any(i[0]=="missing_field" and i[2]==kind for i in r.issues)

def test_omitted_alias_still_conflicts():
    s,l,d,q=fixture()
    l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"alias"),"syn:a","syn:alias"))
    d["records"]["stop"]["alias"]=dict(d["records"]["stop"]["0"],latitude=.001)
    r=run(s,l,d,q)
    assert ("stop","syn:a","latitude") in r.conflicts
    assert ("unexpected_record","syn:data","stop","alias") in r.issues
    assert not r.scoped_certificate
    assert any(o.external_id=="alias" for o in r.observations)

def test_scope_shrink_cannot_match_fixed_reference():
    s,l,d,q=fixture()
    ref=reference(l,(d,),q)
    del q["inventory"]["syn:data"]["stop"]["0"]
    r=run(s,l,d,q,ref)
    assert not r.reference_matches and not r.scoped_certificate
    assert ("unexpected_record","syn:data","stop","0") in r.issues

def test_source_repin_does_not_match_reference():
    s,l,d,q=fixture()
    ref=reference(l,(d,),q)
    d["version"]="v2"
    r=run(s,l,d,q,ref)
    assert r.relative_complete and not r.reference_matches and not r.scoped_certificate

def test_reference_binds_ledger_history():
    s,l,d,q=fixture()
    ref=reference(l,(d,),q)
    l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"new"),"syn:a","syn:new"))
    assert not run(s,l,d,q,ref).reference_matches

def test_model_and_scope_shrink_together():
    s,l,d,q=fixture()
    ref=reference(l,(d,),q)
    s=replace(s,transfers=())
    d["records"]["transfer"].clear()
    q["inventory"]["syn:data"]["transfer"].clear()
    r=run(s,l,d,q,ref)
    assert r.relative_complete and not r.reference_matches and not r.scoped_certificate

def test_nested_visit_order_and_timing_are_checked():
    s,l,d,q=fixture()
    v=d["records"]["trip"]["0"]["visits"]
    v[0],v[-1]=v[-1],v[0]
    assert ("model_mismatch","syn:data","trip","0","visits") in run(s,l,d,q).issues

def test_unresolved_outside_scope_blocks_certificate():
    s,l,d,q=fixture()
    d["records"]["stop"]["orphan"]=d["records"]["stop"]["0"]
    r=run(s,l,d,q)
    assert ("unresolved_identity","syn:data","stop","orphan") in r.issues
    assert not r.scoped_certificate

def test_retired_identity():
    s,l,d,q=fixture()
    l=l.append(Retire(EntityKind.STOP,"syn:a","syn:retire"))
    assert not run(s,l,d,q).scoped_certificate

def test_group_omission_rejected():
    s,l,d,q=fixture()
    del d["records"]["geometry"]
    with pytest.raises(ValueError,match="explicitly"):run(s,l,d,q)

def test_model_preference_does_not_change_conflicts():
    s,l,d,q=fixture()
    l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"alias"),"syn:a","syn:alias"))
    d["records"]["stop"]["alias"]=dict(d["records"]["stop"]["0"],name="Another")
    a=run(s,l,d,q)
    n=s.network
    s=replace(s,network=replace(n,stops=(replace(n.stops[0],name="Another"),)+n.stops[1:]))
    b=run(s,l,d,q)
    assert a.conflicts==b.conflicts==(("stop","syn:a","name"),)
    assert a.observations==b.observations and a.model_sha256!=b.model_sha256

def test_wrong_typed_values_and_extra_fields_fail():
    s,l,d,q=fixture()
    d["records"]["transfer"]["0"]["minimum_seconds"]=True
    d["records"]["agency"]["0"]["extra"]="x"
    r=run(s,l,d,q)
    assert not r.scoped_certificate
    assert ("model_mismatch","syn:data","transfer","0","minimum_seconds") in r.issues

def test_multi_source_order_and_omission():
    s,l,d,q=fixture()
    other=deepcopy(d);other["namespace"]="syn:other"
    inv=deepcopy(q["inventory"]["syn:data"])
    q["inventory"]["syn:other"]=inv
    for k,rs in inv.items():
        for ext,cid in rs.items():
            l=l.append(Bind(SourceKey("syn:other",EntityKind(k),ext),cid,"syn:other-decision"))
    ref=reference(l,(d,other),q)
    a=run(s,l,(d,other),q,ref)
    assert a.scoped_certificate and a==run(s,l,(other,d),q,ref)
    b=run(s,l,d,q,ref)
    assert not b.scoped_certificate and ("missing_source","syn:other") in b.issues

def test_fictional_reference_cannot_authenticate_itself():
    s,l,d,q=fixture()
    assert run(s,l,d,q).scoped_certificate
    assert not run(s,l,d,q).scope_authority_verified
