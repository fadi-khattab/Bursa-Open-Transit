"""Offline synthetic canonical transit model (M2A).

Identity and structural validity are not authorization or source accuracy.
No adapter, network I/O, exporter or publisher is implemented here.
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def ident(value: str) -> None:
    require(type(value) is str and value.startswith("syn:") and
            len(value) > 4 and all(not c.isspace() and c.isprintable() for c in value),
            "M2A requires a nonempty synthetic identifier (syn:...)")


def name(value: str) -> None:
    require(type(value) is str and bool(value.strip()), "name must be nonblank")


def exact_tuple(values: tuple, cls: type, label: str) -> None:
    require(type(values) is tuple and all(type(v) is cls for v in values),
            f"{label}: expected tuple of {cls.__name__}")


def unique(values, label: str) -> None:
    values = tuple(values)
    require(len(values) == len(set(values)), f"duplicate {label}")


def day(value: date) -> None:
    require(type(value) is date, "expected service date (not datetime)")


class Mode(Enum):
    BUS = "bus"
    TRAM = "tram"
    METRO = "metro"


class Timing(Enum):
    KNOWN = "known"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, order=True)
class ServiceTime:
    """Elapsed schedule seconds from service-day origin, not UTC."""
    seconds: int

    def __post_init__(self):
        require(type(self.seconds) is int and self.seconds >= 0,
                "service seconds must be a nonnegative integer")

    @classmethod
    def from_hms(cls, hour: int, minute: int, second: int = 0):
        require(all(type(v) is int for v in (hour, minute, second)) and
                hour >= 0 and 0 <= minute < 60 and 0 <= second < 60,
                "invalid service clock")
        return cls(hour * 3600 + minute * 60 + second)

    def as_hms(self) -> str:
        h, rem = divmod(self.seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass(frozen=True, slots=True)
class Agency:
    id: str
    name: str
    timezone: str

    def __post_init__(self):
        ident(self.id)
        name(self.name)
        require(type(self.timezone) is str and bool(self.timezone),
                "timezone must be a nonempty IANA key")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc


@dataclass(frozen=True, slots=True)
class Stop:
    id: str
    name: str
    latitude: float
    longitude: float

    def __post_init__(self):
        ident(self.id)
        name(self.name)
        for value, bound in ((self.latitude, 90), (self.longitude, 180)):
            require(type(value) in (int, float) and -bound <= value <= bound and
                    isfinite(value), "invalid geographic coordinate")


@dataclass(frozen=True, slots=True)
class Route:
    id: str
    agency_id: str
    name: str
    mode: Mode

    def __post_init__(self):
        ident(self.id)
        ident(self.agency_id)
        name(self.name)
        require(type(self.mode) is Mode, "invalid transport mode")


@dataclass(frozen=True, slots=True)
class Pattern:
    id: str
    route_id: str
    direction: str
    stop_ids: tuple[str, ...]

    def __post_init__(self):
        ident(self.id)
        ident(self.route_id)
        name(self.direction)
        exact_tuple(self.stop_ids, str, "pattern stops")
        require(len(self.stop_ids) >= 2, "pattern needs at least two visits")
        for stop_id in self.stop_ids:
            ident(stop_id)
        # Repeated stop IDs are intentional: visit position disambiguates loops.


@dataclass(frozen=True, slots=True)
class ExceptionDay:
    date: date
    operates: bool

    def __post_init__(self):
        day(self.date)
        require(type(self.operates) is bool, "exception operation must be bool")


@dataclass(frozen=True, slots=True)
class ServiceCalendar:
    id: str
    start: date
    end: date
    weekdays: tuple[int, ...]
    exceptions: tuple[ExceptionDay, ...] = ()

    def __post_init__(self):
        ident(self.id)
        day(self.start)
        day(self.end)
        require(self.start <= self.end, "inverted calendar interval")
        exact_tuple(self.weekdays, int, "weekdays")
        require(all(1 <= x <= 7 for x in self.weekdays), "ISO weekdays must be 1..7")
        unique(self.weekdays, "weekday")
        exact_tuple(self.exceptions, ExceptionDay, "exceptions")
        unique((e.date for e in self.exceptions), "exception date")

    def operates_on(self, service_date: date) -> bool:
        day(service_date)
        for e in self.exceptions:
            if e.date == service_date:
                return e.operates
        return self.start <= service_date <= self.end and service_date.isoweekday() in self.weekdays


@dataclass(frozen=True, slots=True)
class Visit:
    stop_id: str
    arrival: ServiceTime | None
    departure: ServiceTime | None
    timing: Timing

    def __post_init__(self):
        ident(self.stop_id)
        require(type(self.timing) is Timing, "invalid timing classification")
        if self.timing is Timing.UNKNOWN:
            require(self.arrival is None and self.departure is None,
                    "unknown timing must carry no values")
        else:
            require(type(self.arrival) is ServiceTime and type(self.departure) is ServiceTime,
                    "known/estimated visits require both times")
            require(self.arrival <= self.departure, "departure precedes arrival")


@dataclass(frozen=True, slots=True)
class Trip:
    id: str
    pattern_id: str
    service_id: str
    visits: tuple[Visit, ...]

    def __post_init__(self):
        for value in (self.id, self.pattern_id, self.service_id):
            ident(value)
        exact_tuple(self.visits, Visit, "trip visits")
        require(len(self.visits) >= 2, "trip needs at least two visits")
        require(self.visits[0].timing is not Timing.UNKNOWN and
                self.visits[-1].timing is not Timing.UNKNOWN, "trip endpoints require timing")
        previous = None
        for visit in self.visits:
            if visit.timing is not Timing.UNKNOWN:
                require(previous is None or previous <= visit.arrival,
                        "trip timing moves backwards")
                previous = visit.departure


def index(items, cls):
    exact_tuple(items, cls, cls.__name__)
    require(bool(items), f"empty {cls.__name__} collection")
    unique((x.id for x in items), cls.__name__ + " ID")
    return {x.id: x for x in items}


@dataclass(frozen=True, slots=True)
class Network:
    """Synthetic-only development graph; no claim of authenticity."""
    source_id: str
    agencies: tuple[Agency, ...]
    stops: tuple[Stop, ...]
    routes: tuple[Route, ...]
    patterns: tuple[Pattern, ...]
    calendars: tuple[ServiceCalendar, ...]
    trips: tuple[Trip, ...]

    def __post_init__(self):
        ident(self.source_id)
        agencies = index(self.agencies, Agency)
        stops = index(self.stops, Stop)
        routes = index(self.routes, Route)
        patterns = index(self.patterns, Pattern)
        calendars = index(self.calendars, ServiceCalendar)
        index(self.trips, Trip)
        require(len({a.timezone for a in self.agencies}) == 1,
                "M2A requires a single agency timezone per network")
        for r in self.routes:
            require(r.agency_id in agencies, "unknown route agency")
        for p in self.patterns:
            require(p.route_id in routes, "unknown pattern route")
            require(all(s in stops for s in p.stop_ids), "unknown pattern stop")
        for t in self.trips:
            require(t.pattern_id in patterns, "unknown trip pattern")
            require(t.service_id in calendars, "unknown trip service")
            require(tuple(v.stop_id for v in t.visits) == patterns[t.pattern_id].stop_ids,
                    "trip visits must match pattern order and multiplicity")
