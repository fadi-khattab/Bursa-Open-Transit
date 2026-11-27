from dataclasses import replace, FrozenInstanceError
from datetime import date, datetime
import pytest
from bursa_transit.models import (
    Agency, Stop, Route, Pattern, ServiceCalendar, ExceptionDay,
    ServiceTime, Visit, Trip, Network, Mode, Timing,
)
from bursa_transit.models.demo import build_demo


def test_demo_loop_and_timing():
    n = build_demo()
    trip = n.trips[0]
    assert trip.visits[0].stop_id == trip.visits[-1].stop_id
    assert trip.visits[1].timing is Timing.UNKNOWN
    assert trip.visits[2].timing is Timing.ESTIMATED
    assert trip.visits[-1].arrival.as_hms() == "24:20:00"
    assert trip.visits[-1].arrival.seconds - trip.visits[0].departure.seconds == 1500


@pytest.mark.parametrize("h,m,s", [(0,0,0), (23,59,59), (24,0,0), (27,15,30), (100,2,3)])
def test_service_time_roundtrip(h,m,s):
    x = ServiceTime.from_hms(h,m,s)
    assert x.seconds == h*3600+m*60+s
    assert x.as_hms() == f"{h:02d}:{m:02d}:{s:02d}"


@pytest.mark.parametrize("bad", [-1, 0.5, True, "60", None])
def test_invalid_seconds(bad):
    with pytest.raises(ValueError):
        ServiceTime(bad)


@pytest.mark.parametrize("h,m,s", [(-1,0,0), (1,60,0), (1,0,60), (True,0,0), (1,-1,0)])
def test_invalid_clock(h,m,s):
    with pytest.raises(ValueError):
        ServiceTime.from_hms(h,m,s)


@pytest.mark.parametrize("bad", [91,-91,float("nan"),float("inf"),True,"1"])
def test_invalid_latitude(bad):
    with pytest.raises(ValueError):
        Stop("syn:s","Stop",bad,0)


@pytest.mark.parametrize("bad", [181,-181,float("-inf"),None])
def test_invalid_longitude(bad):
    with pytest.raises(ValueError):
        Stop("syn:s","Stop",0,bad)


@pytest.mark.parametrize("bad", ["real:stop","syn:","syn:bad id",None])
def test_invalid_synthetic_ids(bad):
    with pytest.raises(ValueError):
        Stop(bad,"Stop",0,0)


def test_invalid_timezone():
    with pytest.raises(ValueError):
        Agency("syn:a","Operator","Invalid/Zone")


def test_invalid_mode():
    n=build_demo()
    with pytest.raises(ValueError):
        replace(n.routes[0],mode="bus")


@pytest.mark.parametrize("d,expected", [
    (date(2026,11,2),True), (date(2026,11,7),False),
    (date(2026,11,27),False), (date(2026,11,28),True),
    (date(2026,10,31),False), (date(2027,1,1),False),
    (date(2026,12,31),True),
])
def test_calendar(d,expected):
    assert build_demo().calendars[0].operates_on(d) is expected


def test_exception_outside_base_and_exception_only():
    c=ServiceCalendar("syn:cal",date(2026,1,1),date(2026,1,1),(),
                      (ExceptionDay(date(2026,1,2),True),))
    assert not c.operates_on(date(2026,1,1))
    assert c.operates_on(date(2026,1,2))


@pytest.mark.parametrize("kwargs", [
    {"start":date(2027,1,1)}, {"weekdays":(0,)}, {"weekdays":(1,1)},
    {"weekdays":(True,)}, {"weekdays":[1]},
    {"start":datetime(2026,11,1)},
    {"exceptions":(ExceptionDay(date(2026,11,27),True),ExceptionDay(date(2026,11,27),False))},
])
def test_bad_calendar(kwargs):
    with pytest.raises(ValueError):
        replace(build_demo().calendars[0],**kwargs)


def test_service_date_not_shifted_after_midnight():
    n=build_demo()
    cal=n.calendars[0]
    assert cal.operates_on(date(2026,11,26))
    assert not cal.operates_on(date(2026,11,27))
    assert n.trips[0].visits[-1].arrival.seconds > 86400


def test_reject_clock_reversal_across_unknown_visit():
    trip=build_demo().trips[0]
    v=replace(trip.visits[2],arrival=ServiceTime(1),departure=ServiceTime(2))
    with pytest.raises(ValueError,match="backwards"):
        replace(trip,visits=trip.visits[:2]+(v,)+trip.visits[3:])


@pytest.mark.parametrize("index", [0,3])
def test_reject_unknown_endpoints(index):
    trip=build_demo().trips[0]
    visits=list(trip.visits)
    visits[index]=Visit(visits[index].stop_id,None,None,Timing.UNKNOWN)
    with pytest.raises(ValueError,match="endpoints"):
        replace(trip,visits=tuple(visits))


@pytest.mark.parametrize("arr,dep,timing", [
    (ServiceTime(2),ServiceTime(1),Timing.KNOWN),
    (None,ServiceTime(1),Timing.KNOWN),
    (None,None,Timing.ESTIMATED),
    (ServiceTime(1),ServiceTime(1),Timing.UNKNOWN),
    (None,None,"unknown"),
])
def test_bad_visit(arr,dep,timing):
    with pytest.raises(ValueError):
        Visit("syn:s",arr,dep,timing)


@pytest.mark.parametrize("group", ["agencies","stops","routes","patterns","calendars","trips"])
def test_duplicate_ids(group):
    n=build_demo()
    v=getattr(n,group)
    with pytest.raises(ValueError,match="duplicate"):
        replace(n,**{group:v+(v[0],)})


@pytest.mark.parametrize("group", ["agencies","stops","routes","patterns","calendars","trips"])
def test_empty_group(group):
    with pytest.raises(ValueError,match="empty"):
        replace(build_demo(),**{group:()})


@pytest.mark.parametrize("group,field", [
    ("routes","agency_id"),("patterns","route_id"),
    ("trips","pattern_id"),("trips","service_id"),
])
def test_dangling_reference(group,field):
    n=build_demo()
    items=getattr(n,group)
    with pytest.raises(ValueError,match="unknown"):
        replace(n,**{group:(replace(items[0],**{field:"syn:missing"}),)})


def test_dangling_stop():
    n=build_demo()
    with pytest.raises(ValueError,match="unknown pattern stop"):
        replace(n,patterns=(replace(n.patterns[0],stop_ids=("syn:a","syn:missing")),))


def test_order_and_multiplicity():
    n=build_demo()
    p=n.patterns[0]
    with pytest.raises(ValueError,match="pattern order"):
        replace(n,patterns=(replace(p,stop_ids=("syn:a","syn:c","syn:b","syn:a")),))
    with pytest.raises(ValueError,match="pattern order"):
        replace(n,patterns=(replace(p,stop_ids=("syn:a","syn:b","syn:c")),))


def test_immutable_and_no_mutable_collections():
    n=build_demo()
    with pytest.raises(FrozenInstanceError):
        n.source_id="syn:other"
    with pytest.raises(ValueError):
        replace(n,stops=list(n.stops))
    with pytest.raises(ValueError):
        replace(n.patterns[0],stop_ids=list(n.patterns[0].stop_ids))


def test_single_timezone():
    n=build_demo()
    with pytest.raises(ValueError,match="single agency timezone"):
        replace(n,agencies=n.agencies+(Agency("syn:other","Other","UTC"),))


def test_publication_still_denied():
    from bursa_transit.publishing import publication_decision
    assert not publication_decision().allowed
