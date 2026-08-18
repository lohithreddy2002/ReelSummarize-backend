"""
Merge model-extracted place names with geocoding results for persistence and API responses.
"""
from __future__ import annotations

from typing import Any

from domain.models import Location
from schemas import LocationInfo
from services import geocoder as geocoder_module


def structured_locations_by_name(structured_locations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(x.get("name", "")).strip().lower(): x
        for x in structured_locations
        if isinstance(x, dict) and str(x.get("name", "")).strip()
    }


async def merge_locations_for_content(
    content_id: str,
    location_names: list[str],
    structured_locations: list[dict[str, Any]],
    *,
    geocoder_svc: Any | None = None,
) -> list[Location]:
    """
    One row per name in ``location_names`` order. Geocoded rows get coordinates;
    otherwise name (and structured enrichment) are kept with geocoded=False.

    Pass ``geocoder_svc`` (e.g. from ``application.content_service``) so tests can inject a fake.
    """
    gc = geocoder_svc if geocoder_svc is not None else geocoder_module.geocoder
    by_name = structured_locations_by_name(structured_locations)
    pairs = await gc.geocode_many_preserve_names(location_names)
    merged: list[Location] = []
    for raw_name, geo in pairs:
        key = raw_name.strip().lower()
        meta = by_name.get(key) or {}
        if geo:
            merged.append(
                Location(
                    content_id=content_id,
                    name=raw_name.strip(),
                    display_name=geo.display_name,
                    lat=geo.latitude,
                    lng=geo.longitude,
                    geocoded=True,
                    rating=_meta_float(meta, "rating"),
                    review_count=_meta_int(meta, "review_count"),
                    place_category=_meta_str(meta, "place_category"),
                    image_url=_meta_str(meta, "image_url"),
                )
            )
        else:
            merged.append(
                Location(
                    content_id=content_id,
                    name=raw_name.strip(),
                    display_name=_meta_str(meta, "display_name"),
                    lat=None,
                    lng=None,
                    geocoded=False,
                    rating=_meta_float(meta, "rating"),
                    review_count=_meta_int(meta, "review_count"),
                    place_category=_meta_str(meta, "place_category"),
                    image_url=_meta_str(meta, "image_url"),
                )
            )
    return merged


def locations_to_infos(locations: list[Location]) -> list[LocationInfo]:
    return [
        LocationInfo(
            name=loc.name,
            latitude=loc.lat,
            longitude=loc.lng,
            display_name=loc.display_name,
            geocoded=loc.geocoded,
        )
        for loc in locations
    ]


def _meta_str(meta: dict[str, Any], key: str) -> str | None:
    v = meta.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _meta_float(meta: dict[str, Any], key: str) -> float | None:
    v = meta.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _meta_int(meta: dict[str, Any], key: str) -> int | None:
    v = meta.get(key)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
