from dataclasses import FrozenInstanceError, replace
import json
from itertools import combinations
import pytest
from test_pinned_stop_evidence import fixture, pin
from bursa_transit.models.identity import Bind, SourceKey, EntityKind
from bursa_transit.models.derivation import Claim, Rule, _evaluate
from bursa_transit.models.conflicts import ConflictGraph, Selection, Scenario, Status
from bursa_transit.publishing import publication_decision

AB=("syn:a","syn:b")
DIST=Rule.STOP_DISTANCE_M_V1
WALK=Rule.WALK_SECONDS_ESTIMATE_V1
MIN=Rule.SECONDS_TO_MINUTES_V1


def setup(conflict=False, alias=False):
    s,l,d,q=fixture()
    if alias:
        q["stops"]["alias"]="syn:a"
        d["stops"]["alias"]=d["stops"]["0"].copy()
        l=l.append(Bind(SourceKey(d["namespace"],EntityKind.STOP,"alias"),"syn:a","syn:alias"))
    d2=dict(d,namespace="syn:data2",stops={k:v.copy() for k,v in d["stops"].items()})
    q2=dict(q,namespace="syn:scope2",data_namespace="syn:data2",stops=q["stops"].copy())
    for ext,cid in q2["stops"].items():
        l=l.append(Bind(SourceKey("syn:data2",EntityKind.STOP,ext),cid,"syn:decision2-"+ext))
    if conflict:
        d2["stops"]["0"]["latitude"]=.001
    return ConflictGraph(s,l,(Selection(pin(d),pin(q)),Selection(pin(d2),pin(q2))))


def coord_ids(g, ns):
    return tuple(next(p.id for p in g.proofs if p.node and p.node.evidence
                      and p.node.evidence.key.namespace==ns
                      and p.node.subject==(s,) and p.node.field==f)
                 for s in AB for f in ("latitude","longitude"))


def append(g,nid,rule,parents):
    ns=tuple(g.proof(p).node for p in parents)
    _,v,_,_=_evaluate(rule,AB,ns)
    return replace(g,claims=g.claims+(Claim(nid,rule,AB,parents,v),))


def chain(g, ns, suffix):
    d,w,m=("syn:"+x+suffix for x in "dwm")
    g=append(g,d,DIST,coord_ids(g,ns))
    g=append(g,w,WALK,(d,))
    return append(g,m,MIN,(w,))


def alternatives(conflict=False):
    return chain(chain(setup(conflict),"syn:data","1"),"syn:data2","2")


def test_two_replayed_alternatives():
    g=alternatives()
    c=g.conclusion(AB,"great_circle_m")
    assert c.status is Status.CANDIDATE and len(c.alternatives)==2
    assert g.proof("syn:d1").roots != g.proof("syn:d2").roots
    assert not set(g.proof("syn:d1").artifacts)&set(g.proof("syn:d2").artifacts)
    assert json.loads(c.value_json)==pytest.approx(1111.9508)
    assert not g.publication_allowed and not g.source_authenticated
    assert not g.scope_authority_verified and not publication_decision().allowed
    assert replace(g)==g


@pytest.mark.parametrize("nid",["syn:d1","syn:w1","syn:m1"])
def test_quarantine_single_proof_preserves_other_chain(nid):
    g=alternatives()
    h=replace(g,scenario=Scenario((nid,),()))
    assert h.proof(nid).status is Status.QUARANTINED
    assert all(h.proof("syn:"+x+"2").status is Status.CANDIDATE for x in "dwm")
    assert h.conclusion(AB,"illustrative_walk_minutes").status is Status.CANDIDATE
    assert not h.conclusion(AB,"illustrative_walk_minutes").has_nonestimated_candidate
    assert h.proof("syn:m2").node.depends_on_estimate
    assert g.proof(nid).status is Status.CANDIDATE


def test_root_quarantine_preserves_other_path():
    g=alternatives()
    r=coord_ids(g,"syn:data")[0]
    h=replace(g,scenario=Scenario((r,),()))
    assert h.proof(r).status is Status.QUARANTINED
    assert all(h.proof("syn:"+x+"1").status is Status.BLOCKED for x in "dwm")
    assert all(h.proof("syn:"+x+"2").status is Status.CANDIDATE for x in "dwm")


@pytest.mark.parametrize("which",["data","scope"])
def test_artifact_quarantine_covers_all_its_roots(which):
    g=alternatives()
    digest=getattr(g.selections[0],which).expected_sha256
    h=replace(g,scenario=Scenario((),(digest,)))
    assert all(p.status is Status.QUARANTINED for p in h.proofs if p.node and p.node.evidence
               and p.node.evidence.key.namespace=="syn:data")
    assert h.proof("syn:m1").status is Status.BLOCKED
    assert h.proof("syn:m2").status is Status.CANDIDATE


def test_aliases_share_artifact_failure_domain():
    g=setup(alias=True)
    roots=[p for p in g.proofs if p.node and p.node.evidence
           and p.node.evidence.key.namespace=="syn:data" and p.node.subject==("syn:a",)
           and p.node.field=="latitude"]
    assert len(roots)==2 and roots[0].artifacts==roots[1].artifacts
    h=replace(g,scenario=Scenario((),(g.selections[0].data.expected_sha256,)))
    assert all(h.proof(p.id).status is Status.QUARANTINED for p in roots)


def test_disagreement_not_settled_by_model_match():
    g=alternatives(True)
    c=g.conclusion(("syn:a",),"latitude")
    assert c.status is Status.DISPUTED and c.value_json is None
    assert len(c.alternatives)==2
    assert all(g.proof(x).status is Status.DISPUTED for x in c.alternatives)
    assert all(g.proof("syn:"+x+i).status is Status.BLOCKED for x in "dwm" for i in "12")
    assert g.conclusion(("syn:a",),"longitude").status is Status.CANDIDATE
    assert g.conclusion(("syn:b",),"latitude").status is Status.CANDIDATE


@pytest.mark.parametrize("exclude",["syn:data","syn:data2"])
def test_explicit_hypothesis_does_not_prefer_canonical_model(exclude):
    g=alternatives(True)
    r=coord_ids(g,exclude)[0]
    h=replace(g,scenario=Scenario((r,),()))
    other="2" if exclude=="syn:data" else "1"
    blocked="1" if other=="2" else "2"
    assert h.proof("syn:d"+blocked).status is Status.BLOCKED
    assert h.proof("syn:d"+other).status is Status.CANDIDATE
    assert json.loads(h.conclusion(("syn:a",),"latitude").value_json)==(.001 if other=="2" else 0)
    assert not h.source_authenticated and not h.publication_allowed
    assert g.conclusion(("syn:a",),"latitude").status is Status.DISPUTED


def test_invalid_derived_claim_cannot_poison_clean_alternative():
    g=alternatives()
    bad=replace(g.claims[0],value_json="123")
    h=replace(g,claims=(bad,)+g.claims[1:])
    assert h.proof("syn:d1").status is Status.INVALID
    assert h.proof("syn:w1").status is Status.INVALID
    assert h.proof("syn:m1").status is Status.INVALID
    assert h.proof("syn:m2").status is Status.CANDIDATE
    assert h.conclusion(AB,"great_circle_m").status is Status.CANDIDATE


@pytest.mark.parametrize("parents", [("syn:missing",),("syn:future",),("syn:bad",)])
def test_invalid_dependency_isolated(parents):
    g=alternatives()
    bad=Claim("syn:bad",WALK,AB,parents,"1")
    h=replace(g,claims=(bad,)+g.claims)
    assert h.proof("syn:bad").status is Status.INVALID
    assert h.proof("syn:m2").status is Status.CANDIDATE


def test_duplicate_id_fails_closed():
    g=alternatives()
    with pytest.raises(ValueError,match="duplicate"):
        replace(g,claims=g.claims+(g.claims[0],))


def test_unknown_exclusions_fail_closed():
    g=alternatives()
    with pytest.raises(ValueError,match="unknown excluded proof"):
        replace(g,scenario=Scenario(("syn:missing",),()))
    with pytest.raises(ValueError,match="unknown excluded artifact"):
        replace(g,scenario=Scenario((),("0"*64,)))


def test_duplicate_selected_namespace_rejected():
    g=alternatives()
    with pytest.raises(ValueError,match="one selected version"):
        replace(g,selections=g.selections+(g.selections[0],))


def test_no_self_exoneration_from_derivations_or_count():
    g=alternatives(True)
    for i in range(5):
        g=append(g,"syn:duplicate-"+str(i),DIST,coord_ids(g,"syn:data"))
    assert g.conclusion(("syn:a",),"latitude").status is Status.DISPUTED
    assert g.conclusion(AB,"great_circle_m").status is Status.BLOCKED


def test_order_of_independent_sources_does_not_change_results():
    g=alternatives(True)
    h=replace(g,selections=tuple(reversed(g.selections)))
    assert g.proofs==h.proofs and g.conclusions==h.conclusions


def test_model_change_does_not_break_conflict_symmetry():
    g=alternatives(True)
    n=g.spatial.network
    altered=replace(n,stops=(replace(n.stops[0],latitude=.001),)+n.stops[1:])
    h=replace(g,spatial=replace(g.spatial,network=altered))
    assert h.proofs==g.proofs and h.conclusions==g.conclusions
    assert h.audits!=g.audits


def test_immutable_report():
    g=alternatives()
    with pytest.raises(FrozenInstanceError): g.proofs=()
    with pytest.raises(FrozenInstanceError): g.proofs[0].status=Status.CANDIDATE


def test_exhaustive_root_exclusion_oracle():
    g=alternatives()
    ids=coord_ids(g,"syn:data")+coord_ids(g,"syn:data2")
    # Independent oracle: each chain survives iff no root in its own set is excluded.
    for mask in range(256):
        excluded={r for i,r in enumerate(ids) if mask & (1<<i)}
        h=replace(g,scenario=Scenario(tuple(sorted(excluded)),()))
        expected=[]
        for suffix, group in (("1",ids[:4]),("2",ids[4:])):
            survives=not excluded.intersection(group)
            assert (h.proof("syn:m"+suffix).status is Status.CANDIDATE)==survives
            expected.append(survives)
        assert (h.conclusion(AB,"illustrative_walk_minutes").status is Status.CANDIDATE)==any(expected)


def test_equal_derived_outputs_do_not_exonerate_disputed_inputs():
    g=setup()
    d1=g.selections[0].data.document()
    d2=g.selections[1].data.document()
    d1["stops"]["0"]["latitude"]=.001
    d2["stops"]["0"]["latitude"]=-.001
    g=replace(g,selections=(replace(g.selections[0],data=pin(d1)),
                            replace(g.selections[1],data=pin(d2))))
    g=chain(chain(g,"syn:data","1"),"syn:data2","2")
    assert g.proof("syn:d1").node.value_json==g.proof("syn:d2").node.value_json
    assert g.conclusion(("syn:a",),"latitude").status is Status.DISPUTED
    assert g.conclusion(AB,"great_circle_m").status is Status.BLOCKED


def test_shared_parent_failure_blocks_both_paths():
    g=alternatives()
    shared=coord_ids(g,"syn:data")[0]
    mixed=(shared,)+coord_ids(g,"syn:data2")[1:]
    g=append(g,"syn:mixed",DIST,mixed)
    h=replace(g,scenario=Scenario((shared,),()))
    assert h.proof("syn:d1").status is Status.BLOCKED
    assert h.proof("syn:mixed").status is Status.BLOCKED
    assert h.proof("syn:d2").status is Status.CANDIDATE


def test_scope_omission_is_visible_but_not_a_global_conflict_certificate():
    g=setup(alias=True)
    d=g.selections[0].data.document()
    q=g.selections[0].scope.document()
    d["stops"]["alias"]["latitude"]=.001
    del q["stops"]["alias"]
    h=replace(g,selections=(Selection(pin(d),pin(q)),g.selections[1]))
    assert "alias" in h.audits[0].unexpected_source_ids
    assert not h.audits[0].relative_complete
    # Deliberately scoped: an out-of-scope record is not used as a root.
    assert h.conclusion(("syn:a",),"latitude").status is Status.CANDIDATE
    assert not h.scope_authority_verified and not h.publication_allowed
