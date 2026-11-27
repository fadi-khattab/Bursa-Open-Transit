"""M2B: offline geography and occurrence-aware directed topology."""
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt, isfinite
from . import Network, ident, name, require, exact_tuple, unique

@dataclass(frozen=True, slots=True)
class Point:
    latitude: float
    longitude: float

    def __post_init__(self):
        for v, bound in ((self.latitude, 90), (self.longitude, 180)):
            require(type(v) in (int, float) and -bound <= v <= bound and isfinite(v),
                    "invalid coordinate")

def distance_m(a: Point, b: Point) -> float:
    """Spherical great-circle approximation, not surveyed or road distance."""
    require(type(a) is Point and type(b) is Point, "expected Point")
    p, q = radians(a.latitude), radians(b.latitude)
    d = radians(b.longitude - a.longitude)
    h = sin((q-p)/2)**2 + cos(p)*cos(q)*sin(d/2)**2
    return 2*6371008.8*asin(sqrt(min(1.0,max(0.0,h))))

@dataclass(frozen=True, slots=True)
class Shape:
    id: str
    points: tuple[Point, ...]

    def __post_init__(self):
        ident(self.id)
        exact_tuple(self.points, Point, "shape vertices")
        require(len(self.points)>=2, "shape needs at least two vertices")
        require(all(distance_m(a,b)>0.001 for a,b in zip(self.points,self.points[1:])),
                "consecutive shape points must be distinct")

    def cumulative_m(self) -> tuple[float,...]:
        out = [0.0]
        for a,b in zip(self.points,self.points[1:]):
            out.append(out[-1]+distance_m(a,b))
        return tuple(out)

@dataclass(frozen=True, slots=True)
class PatternGeometry:
    pattern_id: str
    shape_id: str
    vertex_indices: tuple[int,...]

    def __post_init__(self):
        ident(self.pattern_id)
        ident(self.shape_id)
        exact_tuple(self.vertex_indices, int, "visit anchor indices")
        require(len(self.vertex_indices)>=2 and all(i>=0 for i in self.vertex_indices),
                "invalid anchors")
        require(all(a<=b for a,b in zip(self.vertex_indices,self.vertex_indices[1:])),
                "anchors move backwards")

@dataclass(frozen=True, slots=True)
class StationArea:
    id: str
    name: str
    stop_ids: tuple[str,...]

    def __post_init__(self):
        ident(self.id)
        name(self.name)
        exact_tuple(self.stop_ids, str, "station area children")
        require(bool(self.stop_ids), "empty station area")
        for s in self.stop_ids: ident(s)
        unique(self.stop_ids,"station area child")

@dataclass(frozen=True, slots=True)
class Transfer:
    from_stop: str
    to_stop: str
    minimum_seconds: int

    def __post_init__(self):
        ident(self.from_stop)
        ident(self.to_stop)
        require(self.from_stop != self.to_stop, "self-transfer not represented")
        require(type(self.minimum_seconds) is int and self.minimum_seconds>=0,
                "invalid transfer duration")

@dataclass(frozen=True, slots=True)
class SpatialNetwork:
    network: Network
    shapes: tuple[Shape,...] = ()
    geometry: tuple[PatternGeometry,...] = ()
    areas: tuple[StationArea,...] = ()
    transfers: tuple[Transfer,...] = ()
    # Explicit synthetic acceptance threshold; not an agency quality policy.
    max_anchor_offset_m: float = 50.0

    def __post_init__(self):
        require(type(self.network) is Network,"expected Network")
        for values,cls in ((self.shapes,Shape),(self.geometry,PatternGeometry),
                           (self.areas,StationArea),(self.transfers,Transfer)):
            exact_tuple(values,cls,cls.__name__)
        v=self.max_anchor_offset_m
        require(type(v) in (int,float) and 0<=v<=1000 and isfinite(v),"invalid anchor tolerance")
        unique((x.id for x in self.shapes),"shape ID")
        unique((x.pattern_id for x in self.geometry),"pattern geometry")
        unique((x.id for x in self.areas),"station area ID")
        unique((s for x in self.areas for s in x.stop_ids),"station membership")
        unique(((x.from_stop,x.to_stop) for x in self.transfers),"directed transfer")
        stops={s.id:s for s in self.network.stops}
        patterns={p.id:p for p in self.network.patterns}
        shapes={s.id:s for s in self.shapes}
        require(not (set(stops)&{a.id for a in self.areas}),"stop/station ID collision")
        for area in self.areas:
            require(all(s in stops for s in area.stop_ids),"unknown station child")
        for edge in self.transfers:
            require(edge.from_stop in stops and edge.to_stop in stops,"unknown transfer stop")
        for g in self.geometry:
            require(g.pattern_id in patterns and g.shape_id in shapes,"unknown geometry reference")
            pattern=patterns[g.pattern_id]
            shape=shapes[g.shape_id]
            require(len(g.vertex_indices)==len(pattern.stop_ids),"anchor count must match visits")
            require(g.vertex_indices[-1]<len(shape.points),"anchor outside shape")
            for s,i in zip(pattern.stop_ids,g.vertex_indices):
                stop=stops[s]
                require(distance_m(Point(stop.latitude,stop.longitude),shape.points[i])<=v,
                        "stop anchor exceeds tolerance")

    def occurrence_distances(self, pattern_id: str) -> tuple[float,...] | None:
        """No geometry means unknown; never synthesize a path."""
        require(any(p.id==pattern_id for p in self.network.patterns),"unknown pattern")
        for g in self.geometry:
            if g.pattern_id==pattern_id:
                shape=next(s for s in self.shapes if s.id==g.shape_id)
                distances=shape.cumulative_m()
                return tuple(distances[i] for i in g.vertex_indices)
        return None

    def ride_edges(self) -> tuple[tuple[str,int,str,str],...]:
        """Directed occurrence edges: (pattern ID, position, from, to)."""
        return tuple((p.id,i,a,b) for p in self.network.patterns
                     for i,(a,b) in enumerate(zip(p.stop_ids,p.stop_ids[1:])))
