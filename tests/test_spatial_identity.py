from dataclasses import replace
import math
import pytest
from bursa_transit.models.demo import build_demo
from bursa_transit.models.spatial import (
    Point, distance_m, Shape, PatternGeometry, StationArea, Transfer, SpatialNetwork)
from bursa_transit.models.identity import EntityKind, SourceKey, Bind, Retire, IdentityLedger

def shape():
    return Shape("syn:shape",(Point(0,0),Point(0,.01),Point(.01,.01),Point(0,0)))

def geometry():
    return PatternGeometry("syn:pattern","syn:shape",(0,1,2,3))

def spatial(**kwargs):
    return SpatialNetwork(build_demo(),**kwargs)

def test_loop_anchor_identity():
    n=spatial(shapes=(shape(),),geometry=(geometry(),))
    distances=n.occurrence_distances("syn:pattern")
    assert distances[0]==0 and distances[0]<distances[1]<distances[2]<distances[3]
    assert n.ride_edges()[0]==("syn:pattern",0,"syn:a","syn:b")
    assert n.ride_edges()[-1]==("syn:pattern",2,"syn:c","syn:a")

def test_missing_geometry_explicit():
    assert spatial().occurrence_distances("syn:pattern") is None
    with pytest.raises(ValueError): spatial().occurrence_distances("syn:missing")

@pytest.mark.parametrize("lat,lon",[(91,0),(-91,0),(0,181),(0,-181),(math.nan,0),(0,math.inf),(True,0),("0",0)])
def test_coordinates(lat,lon):
    with pytest.raises(ValueError): Point(lat,lon)

def test_distance_reference():
    assert distance_m(Point(0,0),Point(0,1))==pytest.approx(math.pi*6371008.8/180)
    assert distance_m(Point(0,179.9),Point(0,-179.9))==pytest.approx(math.pi*6371008.8*.2/180)
    assert distance_m(Point(0,0),Point(0,180))==pytest.approx(math.pi*6371008.8)
    assert distance_m(Point(0,0),Point(0,0))==0

@pytest.mark.parametrize("points", [(),(Point(0,0),),(Point(0,0),Point(0,0))])
def test_invalid_shape(points):
    with pytest.raises(ValueError): Shape("syn:shape",points)

@pytest.mark.parametrize("indices",[(0,2,1,3),(-1,1,2,3),(0,True,2,3),(0,)])
def test_invalid_anchors(indices):
    with pytest.raises(ValueError): replace(geometry(),vertex_indices=indices)

@pytest.mark.parametrize("changes",[
    {"pattern_id":"syn:missing"},{"shape_id":"syn:missing"},
    {"vertex_indices":(0,1,3)},{"vertex_indices":(0,1,2,4)},
    {"vertex_indices":(0,0,2,3)}])
def test_invalid_geometry(changes):
    with pytest.raises(ValueError): spatial(shapes=(shape(),),geometry=(replace(geometry(),**changes),))

def test_duplicates():
    with pytest.raises(ValueError): spatial(shapes=(shape(),shape()))
    with pytest.raises(ValueError): spatial(shapes=(shape(),),geometry=(geometry(),geometry()))

@pytest.mark.parametrize("tolerance",[-1,1001,float("nan"),True])
def test_tolerance(tolerance):
    with pytest.raises(ValueError): spatial(max_anchor_offset_m=tolerance)

def test_station_and_transfer_direction():
    area=StationArea("syn:station","Fictional station",("syn:a","syn:b"))
    transfer=Transfer("syn:a","syn:b",45)
    n=spatial(areas=(area,),transfers=(transfer,))
    assert n.transfers==(transfer,)
    assert not any(t.from_stop=="syn:b" for t in n.transfers)
    assert spatial(areas=(area,)).transfers==()

@pytest.mark.parametrize("args",[("syn:a","syn:a",0),("syn:a","syn:b",-1),("syn:a","syn:b",True)])
def test_invalid_transfer(args):
    with pytest.raises(ValueError): Transfer(*args)

def test_bad_area_and_transfer_refs():
    a=StationArea("syn:station","Station",("syn:a",))
    with pytest.raises(ValueError): spatial(areas=(a,replace(a,id="syn:station2")))
    with pytest.raises(ValueError): spatial(areas=(replace(a,id="syn:a"),))
    with pytest.raises(ValueError): spatial(areas=(replace(a,stop_ids=("syn:missing",)),))
    t=Transfer("syn:a","syn:b",0)
    with pytest.raises(ValueError): spatial(transfers=(t,t))
    with pytest.raises(ValueError): spatial(transfers=(replace(t,to_stop="syn:missing"),))

def key(raw="A",kind=EntityKind.STOP,namespace="syn:source"):
    return SourceKey(namespace,kind,raw)

def bind(k=None,canonical="syn:canonical"):
    return Bind(k if k is not None else key(),canonical,"syn:decision")

def test_identity_replay_and_reordering():
    k1,k2=key(),key("B")
    ledger=IdentityLedger().append(bind(k1)).append(bind(k2,"syn:second"))
    assert ledger.resolve_snapshot((k2,k1))==("syn:second","syn:canonical")
    assert ledger.resolve_snapshot((k1,))==("syn:canonical",)
    assert ledger.resolve(k2)=="syn:second"
    assert IdentityLedger(ledger.events)==ledger

def test_explicit_alias_and_no_implicit_match():
    a,b=key(),key("new",namespace="syn:other")
    ledger=IdentityLedger().append(bind(a))
    assert ledger.resolve(b) is None
    updated=ledger.append(bind(b))
    assert updated.resolve(a)==updated.resolve(b)=="syn:canonical"
    assert ledger.resolve(b) is None

def test_typed_identity_and_namespace():
    a,b,c=key(),key(kind=EntityKind.ROUTE),key(namespace="syn:other")
    ledger=IdentityLedger().append(bind(a)).append(bind(b,"syn:route"))
    assert ledger.resolve(b)=="syn:route"
    assert ledger.resolve(c) is None

@pytest.mark.parametrize("canonical",["syn:canonical","syn:other"])
def test_rebind_rejected(canonical):
    ledger=IdentityLedger().append(bind())
    with pytest.raises(ValueError): ledger.append(bind(canonical=canonical))

def test_retirement_no_resurrection_or_reuse():
    a,b=key(),key("B")
    ledger=IdentityLedger().append(bind(a)).append(bind(b))
    retired=ledger.append(Retire(EntityKind.STOP,"syn:canonical","syn:decision2"))
    assert retired.resolve(a) is None and retired.resolve(b) is None
    assert retired.historical_id(a)=="syn:canonical"
    for e in (bind(key("C")),bind(a,"syn:new"),Retire(EntityKind.STOP,"syn:canonical","syn:d")):
        with pytest.raises(ValueError): retired.append(e)
    assert ledger.resolve(a)=="syn:canonical"

def test_retire_unknown():
    with pytest.raises(ValueError): IdentityLedger().append(Retire(EntityKind.STOP,"syn:missing","syn:d"))

def test_replay_rejects_invalid_history():
    with pytest.raises(ValueError): IdentityLedger((bind(),bind()))
    with pytest.raises(ValueError): IdentityLedger([bind()])

def test_identity_independent_of_spatial_metadata():
    k=key()
    ledger=IdentityLedger().append(bind(k))
    stop=build_demo().stops[0]
    moved=replace(stop,name="Renamed",latitude=.0001)
    assert moved!=stop and ledger.resolve(k)=="syn:canonical"

@pytest.mark.parametrize("raw",[""," ","x y","x\n"])
def test_invalid_key(raw):
    with pytest.raises(ValueError): key(raw)
