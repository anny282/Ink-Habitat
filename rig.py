"""Attach creature strokes into a simple parent/child rig.

A pivot is the point at the end of a stroke where it hangs from its parent.
All geometry stays in creature-local coordinates.
"""
from __future__ import annotations

from math import hypot
from typing import Any


def _valid_points(part: dict[str, Any]) -> list[tuple[float, float]]:
    points = []
    for point in part.get("points", []):
        if (
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((float(point[0]), float(point[1])))
    return points


def _project(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
    projected = (a[0] + t * dx, a[1] + t * dy)
    return hypot(point[0] - projected[0], point[1] - projected[1]), projected


def _nearest_on_stroke(point: tuple[float, float], points: list[tuple[float, float]]):
    if len(points) == 1:
        return hypot(point[0] - points[0][0], point[1] - points[0][1]), points[0]
    return min((_project(point, a, b) for a, b in zip(points, points[1:])), key=lambda hit: hit[0])


def _body_index(parts: list[dict[str, Any]], paths: list[list[tuple[float, float]]]) -> int:
    marked = [i for i, part in enumerate(parts) if part.get("role") == "body"]
    if marked:
        return marked[0]

    def area(i: int) -> float:
        points = paths[i]
        if not points:
            return 0.0
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    return max(range(len(parts)), key=area)


def rig_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill parent, pivot and z in place, then return the parts list.

    The marked body is the root (or the largest bounding-box stroke if no body is marked).
    Other strokes attach to the nearest stroke that has already been attached.
    """
    if not parts:
        return parts
    paths = [_valid_points(part) for part in parts]
    root_i = _body_index(parts, paths)
    root = parts[root_i]
    root["parent"], root["pivot"], root["role"], root["moves"], root["z"] = None, [0, 0], "body", False, 0

    attached = [root_i]
    remaining = [i for i in range(len(parts)) if i != root_i]
    while remaining:
        best = None
        # At each step, attach whichever remaining stroke is closest to any attached stroke.
        for child_i in remaining:
            child_points = paths[child_i]
            if not child_points:
                continue
            ends = [child_points[0], child_points[-1]]
            for parent_i in attached:
                parent_points = paths[parent_i]
                if not parent_points:
                    continue
                for end_i, endpoint in enumerate(ends):
                    distance, _ = _nearest_on_stroke(endpoint, parent_points)
                    candidate = (distance, child_i, parent_i, end_i)
                    if best is None or candidate < best:
                        best = candidate
        if best is None:
            # Empty or malformed strokes still join the root and remain harmless.
            child_i, parent_i, end_i = remaining[0], root_i, 0
            pivot = [0, 0]
        else:
            _, child_i, parent_i, end_i = best
            endpoint = paths[child_i][0 if end_i == 0 else -1]
            pivot = [round(endpoint[0]), round(endpoint[1])]
        child = parts[child_i]
        child["parent"] = parts[parent_i].get("id")
        child["pivot"] = pivot
        child["z"] = _z_for_child(child, paths[child_i], paths[root_i])
        attached.append(child_i)
        remaining.remove(child_i)

    return parts


def _z_for_child(part: dict[str, Any], points: list[tuple[float, float]], body: list[tuple[float, float]]) -> int:
    role = part.get("role")
    if role in {"leg", "tail", "wing"}:
        return -1
    if role in {"head", "eye", "arm", "decoration"}:
        return 1
    if not points or not body:
        return 1
    # Before role classification, put strokes below the body center behind it;
    # strokes above the center (often eyes, ears or decorations) stay in front.
    body_y = sum(point[1] for point in body) / len(body)
    part_y = sum(point[1] for point in points) / len(points)
    return -1 if part_y > body_y else 1


# Short alias for callers that prefer the name in the spec.
rig = rig_parts
