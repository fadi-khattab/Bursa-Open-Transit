from dataclasses import FrozenInstanceError, replace
import json
import math
import pytest
from test_pinned_stop_evidence import fixture, pin
from bursa_transit.models.derivation import Claim, DerivationGraph, Origin, Rule
from bursa_transit.models.identity import Bind, EntityKind, SourceKey
from bursa_transit.publishing import publication_decision

AB = ("syn:a", "syn:b")
DIST = Rule.STOP_DISTANCE_M_V1
WALK = Rule.WALK_SECONDS_ESTIMATE_V1
MIN = Rule.SECONDS_TO_MINUTES_V1

def graph(parts=None):
    s,l,d,q = fixture() if parts is None else parts
    return DerivationGraph(s,l,pin(d),pin(q))

def coords(g, subject=AB):
    return tuple(g.original(s,f)[0].id for s in subject for f in ("latitude","longitude"))

def distance(g=None):
    g = graph() if g is None else g
    return g.derive("syn:d",DIST,AB,coords(g))

def chain():
    return distance().derive("syn:w",WALK,AB,("syn:d",)).derive("syn:m",MIN,AB,("syn:w",))

def test_pinned_roots_and_determinism():
    g=graph()
    assert len(g.nodes)==9 and g==graph()
    assert all(n.evidence and n.origin is Origin.ORIGINAL and not n.depends_on_estimate for n in g.nodes)
    assert all(n.evidence.source_sha256==g.data.expected_sha256 for n in g.nodes)

def test_verified_distance_independent_reference():
    n=distance().node("syn:d")
    assert json.loads(n.value_json)==pytest.approx(math.pi*6371008.8*.01/180,rel=1e-12)
    assert n.origin is Origin.DERIVED and not n.depends_on_estimate

def test_estimation_propagates_and_replay():
    g=chain()
    assert g.node("syn:w").origin is Origin.ESTIMATED
    assert g.node("syn:m").origin is Origin.DERIVED
    assert g.node("syn:w").depends_on_estimate and g.node("syn:m").depends_on_estimate
    assert json.loads(g.node("syn:w").value_json)==927
    assert json.loads(g.node("syn:m").value_json)==15.45
    assert replace(g)==g

@pytest.mark.parametrize("bad",["0","999","true","NaN","1e999","null","{}","[]"])
def test_fabricated_computed_result_rejected(bad):
    g=distance()
    with pytest.raises(ValueError,match="recomputation"):
        replace(g,claims=(replace(g.claims[0],value_json=bad),))

def test_unknown_rule():
    with pytest.raises(ValueError,match="unknown rule"):
        Claim("syn:x","distance",AB,(),"0")

@pytest.mark.parametrize("mutation",["self","future","missing","duplicate","reordered","wrong_subject","wrong_rule"])
def test_bad_graph(mutation):
    g=chain()
    a,b,c=g.claims
    if mutation=="self": claims=(replace(a,parents=(a.id,)),)
    elif mutation=="future": claims=(b,a,c)
    elif mutation=="missing": claims=(replace(a,parents=("syn:absent",)),)
    elif mutation=="duplicate": claims=(a,a)
    elif mutation=="reordered": claims=(replace(a,parents=tuple(reversed(a.parents))),)
    elif mutation=="wrong_subject": claims=(replace(a,subject=("syn:b","syn:a")),)
    else: claims=(replace(a,rule=WALK),)
    with pytest.raises(ValueError): replace(g,claims=claims)

def test_root_collision():
    g=graph()
    with pytest.raises(ValueError,match="duplicate node"):
        g.derive(g.nodes[0].id,DIST,AB,coords(g))

def test_duplicate_parent():
    g=graph()
    with pytest.raises(ValueError,match="duplicate parent"):
        Claim("syn:x",DIST,AB,(g.nodes[0].id,)*4,"0")

def test_no_mutable_claim_list():
    g=distance()
    with pytest.raises(ValueError): replace(g,claims=list(g.claims))
    with pytest.raises(FrozenInstanceError): g.nodes=()
    with pytest.raises(FrozenInstanceError): g.nodes[0].value_json="0"
    with pytest.raises(FrozenInstanceError): g.claims[0].value_json="0"

def test_append_preserves_original():
    g=graph()
    h=distance(g)
    assert len(g.nodes)==9 and len(h.nodes)==10
    assert h.nodes[:9]==g.nodes

def test_missing_field_does_not_become_root():
    s,l,d,q=fixture()
    del d["stops"]["0"]["latitude"]
    g=graph((s,l,d,q))
    assert not g.audit.relative_complete and not g.original("syn:a","latitude")
    assert g.original("syn:b","latitude")

def test_missing_unrelated_record_does_not_disable_derivation():
    s,l,d,q=fixture()
    del d["stops"]["2"]
    g=distance(graph((s,l,d,q)))
    assert not g.audit.relative_complete and g.node("syn:d")

def test_mismatch_cannot_be_root():
    s,l,d,q=fixture()
    d["stops"]["0"]["latitude"]=.001
    g=graph((s,l,d,q))
    assert not g.original("syn:a","latitude")
    assert not g.audit.relative_complete

def test_disputed_alias_blocks_field_not_unrelated_field():
    s,l,d,q=fixture()
    q["stops"]["alias"]="syn:a"
    d["stops"]["alias"]=dict(d["stops"]["0"],latitude=.001)
    l=l.append(Bind(SourceKey("syn:data",EntityKind.STOP,"alias"),"syn:a","syn:alias"))
    g=graph((s,l,d,q))
    assert not g.original("syn:a","latitude")
    assert len(g.original("syn:a","longitude"))==2
    assert g.original("syn:b","latitude")

def test_stale_claim_after_snapshot_change():
    s,l,d,q=fixture()
    g=distance(graph((s,l,d,q)))
    d["version"]="v2"
    q["data_version"]="v2"
    with pytest.raises(ValueError,match="parent absent"):
        replace(g,data=pin(d),scope=pin(q))

def test_no_authority_from_success():
    g=chain()
    assert g.audit.relative_complete
    assert not g.source_authenticated and not g.scope_authority_verified
    assert not g.publication_allowed and not publication_decision().allowed

def test_result_with_estimate_cannot_impersonate_coordinates():
    g=chain()
    with pytest.raises(ValueError,match="signature"):
        g.derive("syn:fake",DIST,AB,("syn:m",)+coords(g)[1:])

def test_distinct_subject_required():
    with pytest.raises(ValueError):
        Claim("syn:x",DIST,("syn:a","syn:a"),(),"0")

def test_foreign_subject_rejected():
    g=graph()
    with pytest.raises(ValueError,match="signature"):
        g.derive("syn:x",DIST,("syn:a","syn:c"),coords(g))

def test_missing_parent_cannot_be_generated():
    with pytest.raises(ValueError,match="unknown node"):
        graph().derive("syn:x",WALK,AB,("syn:missing",))
