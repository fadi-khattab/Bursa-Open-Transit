"""Fictional local model; not a representation of Bursa transport."""
from datetime import date
from bursa_transit.models import (
    Agency, Stop, Route, Pattern, ServiceCalendar, ExceptionDay,
    ServiceTime, Visit, Trip, Network, Mode, Timing,
)


def build_demo() -> Network:
    a = Agency("syn:agency", "Fictional operator", "Europe/Istanbul")
    stops = (Stop("syn:a", "Fictional A", 0.0, 0.0),
             Stop("syn:b", "Fictional B", 0.0, 0.01),
             Stop("syn:c", "Fictional C", 0.01, 0.01))
    r = Route("syn:route", a.id, "Fictional loop", Mode.BUS)
    p = Pattern("syn:pattern", r.id, "loop", ("syn:a", "syn:b", "syn:c", "syn:a"))
    cal = ServiceCalendar("syn:weekday", date(2026, 11, 1), date(2026, 12, 31),
                          (1, 2, 3, 4, 5),
                          (ExceptionDay(date(2026, 11, 27), False),
                           ExceptionDay(date(2026, 11, 28), True)))
    def t(h, m):
        return ServiceTime.from_hms(h, m)
    trip = Trip("syn:trip", p.id, cal.id, (
        Visit("syn:a", t(23, 55), t(23, 55), Timing.KNOWN),
        Visit("syn:b", None, None, Timing.UNKNOWN),
        Visit("syn:c", t(24, 8), t(24, 9), Timing.ESTIMATED),
        Visit("syn:a", t(24, 20), t(24, 20), Timing.KNOWN),
    ))
    return Network("syn:demo-v1", (a,), stops, (r,), (p,), (cal,), (trip,))
