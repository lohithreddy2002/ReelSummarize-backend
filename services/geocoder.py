"""
Geocoding service.

Provider selection (automatic, no config required):
  - MAPBOX_ACCESS_TOKEN set  -> Mapbox Geocoding API
  - GOOGLE_MAPS_API_KEY set  -> Google Cloud Geocoding API
  - neither set              -> Nominatim (OpenStreetMap) - free, 1 req/s limit

Nominatim ToS: https://operations.osmfoundation.org/policies/nominatim/
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional
from urllib.parse import quote

import httpx

from config import GOOGLE_MAPS_API_KEY, MAPBOX_ACCESS_TOKEN

logger = logging.getLogger(__name__)

# Nominatim requires a descriptive User-Agent per its ToS
_NOMINATIM_UA = "ReelSummarize/1.0 (contact: support@reelsummarize.app)"

# Nominatim allows max 1 req/sec across the process
_nominatim_lock = asyncio.Lock()
_NOMINATIM_DELAY = 1.1  # seconds between requests


class GeocodingError(Exception):
    """Custom exception for geocoding errors"""
    pass


class Location:
    """Represents a geocoded location."""

    def __init__(self, name: str, latitude: float, longitude: float, display_name: str = ""):
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.display_name = display_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "display_name": self.display_name,
        }


class Geocoder:
    """
    Geocoding service.  Uses Google Maps when configured, otherwise Nominatim.
    """

    _GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    _MAPBOX_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"
    _NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    # Phrases that indicate no location was extracted
    NO_LOCATION_PHRASES = [
        'none mentioned', 'none', 'n/a', 'not mentioned',
        'no specific', 'no locations', 'not specified',
        'none were mentioned', 'no places', 'not applicable',
        'no location', 'unidentified', 'unknown location',
        'no geographical', 'not identifiable', 'indoors',
        'indoor setting', 'unspecified',
    ]

    SKIP_PHRASES = [
        'the video', 'this video', 'the reel', 'various',
        'multiple locations', 'several places', 'different areas',
        'background', 'setting', 'scene', 'shot', 'frame',
        'mentioned', 'shown', 'visible', 'appears', 'featured',
    ]

    DESCRIPTORS_TO_REMOVE = [
        r'\(.*?\)',
        r'\[.*?\]',
        r'(?:^|\s)(?:the|a|an)\s+',
        r'(?:\s*[-–—]\s*.+)$',
        r'(?:,\s*(?:which|where|that|a|the)\s+.+)$',
    ]

    def __init__(self) -> None:
        self._mapbox_token: str = MAPBOX_ACCESS_TOKEN or ""
        self._use_mapbox: bool = bool(self._mapbox_token)
        self._google_key: str = GOOGLE_MAPS_API_KEY or ""
        self._use_google: bool = bool(self._google_key) and not self._use_mapbox
        self._client: Optional[httpx.AsyncClient] = None
        if self._use_mapbox:
            logger.info("geocoder: using Mapbox")
        elif self._use_google:
            logger.info("geocoder: using Google Maps")
        else:
            logger.info("geocoder: no MAPBOX_ACCESS_TOKEN/GOOGLE_MAPS_API_KEY set — using Nominatim (OpenStreetMap)")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    # ------------------------------------------------------------------
    # Name cleaning / validation
    # ------------------------------------------------------------------

    def _clean_location_name(self, name: str) -> str:
        cleaned = name.strip()
        cleaned = re.sub(r'^(?:at|in|near|around|from|to)\s+', '', cleaned, flags=re.IGNORECASE)
        for pattern in self.DESCRIPTORS_TO_REMOVE:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip('"\'""''')
        cleaned = cleaned.rstrip('.,;:!?')
        cleaned = ' '.join(cleaned.split())
        return cleaned.strip()

    def _is_valid_location(self, name: str) -> bool:
        name_lower = name.lower()
        if len(name) < 2 or len(name) > 100:
            return False
        # SKIP_PHRASES use substring match (they're multi-word and specific)
        if any(phrase in name_lower for phrase in self.SKIP_PHRASES):
            return False
        # NO_LOCATION_PHRASES use whole-word match to avoid false positives
        # e.g. "studio" must not reject "Cafe Studio, Bangalore"
        if any(re.search(r'\b' + re.escape(phrase) + r'\b', name_lower) for phrase in self.NO_LOCATION_PHRASES):
            return False
        if sum(c.isdigit() for c in name) > len(name) / 2:
            return False
        if not any(c.isalpha() for c in name):
            return False
        if len(name.split()) > 12:
            return False
        return True

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _geocode_google(self, cleaned_name: str) -> Optional[Location]:
        try:
            resp = await self._get_client().get(
                self._GOOGLE_URL,
                params={"address": cleaned_name, "key": self._google_key},
            )
            if resp.status_code != 200:
                logger.warning("google geocode HTTP %s for '%s'", resp.status_code, cleaned_name)
                return None
            data = resp.json()
            status = data.get("status", "")
            if status != "OK":
                logger.debug("google geocode status=%s for '%s'", status, cleaned_name)
                return None
            results = data.get("results", [])
            if not results:
                return None
            loc = results[0].get("geometry", {}).get("location", {})
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                return None
            return Location(
                name=cleaned_name,
                latitude=float(lat),
                longitude=float(lng),
                display_name=results[0].get("formatted_address", cleaned_name),
            )
        except Exception:
            logger.exception("google geocode error for '%s'", cleaned_name)
            return None

    async def _geocode_mapbox(self, cleaned_name: str) -> Optional[Location]:
        try:
            resp = await self._get_client().get(
                self._MAPBOX_URL.format(query=quote(cleaned_name, safe="")),
                params={"access_token": self._mapbox_token, "limit": 1},
            )
            if resp.status_code != 200:
                logger.warning("mapbox geocode HTTP %s for '%s'", resp.status_code, cleaned_name)
                return None
            data = resp.json()
            features = data.get("features", [])
            if not features:
                return None
            feature = features[0]
            center = feature.get("center", [])
            if len(center) != 2:
                return None
            lng, lat = center
            return Location(
                name=cleaned_name,
                latitude=float(lat),
                longitude=float(lng),
                display_name=feature.get("place_name", cleaned_name),
            )
        except Exception:
            logger.exception("mapbox geocode error for '%s'", cleaned_name)
            return None

    async def _nominatim_query(self, query: str) -> Optional[Location]:
        """Single Nominatim HTTP call. Caller must hold _nominatim_lock."""
        try:
            resp = await self._get_client().get(
                self._NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": "1"},
                headers={"User-Agent": _NOMINATIM_UA},
            )
            if resp.status_code != 200:
                logger.warning("nominatim HTTP %s for '%s'", resp.status_code, query)
                return None
            results = resp.json()
            if not results:
                return None
            r = results[0]
            return Location(
                name=query,
                latitude=float(r["lat"]),
                longitude=float(r["lon"]),
                display_name=r.get("display_name", query),
            )
        except Exception:
            logger.exception("nominatim geocode error for '%s'", query)
            return None

    async def _geocode_nominatim(self, cleaned_name: str) -> Optional[Location]:
        """
        Nominatim with progressive fallback: if the full name returns nothing,
        drop the leading segment (the venue name) and retry with the area/city.

        E.g. "Manah Cafe Studio, Jayanagar, Bangalore, India"
             → retry "Jayanagar, Bangalore, India"
             → retry "Bangalore, India"

        Caller must hold _nominatim_lock.  Each attempt sleeps _NOMINATIM_DELAY.
        """
        parts = [p.strip() for p in cleaned_name.split(",")]
        queries = [cleaned_name]
        # Build fallback queries by dropping the first segment each time,
        # but only when there are at least 2 segments remaining (city-level min)
        for i in range(1, len(parts) - 1):
            queries.append(", ".join(parts[i:]))

        for i, query in enumerate(queries):
            if i > 0:
                # Extra delay for each additional attempt
                await asyncio.sleep(_NOMINATIM_DELAY)
            result = await self._nominatim_query(query)
            if result:
                if i > 0:
                    logger.info("nominatim: fell back to '%s' for original '%s'", query, cleaned_name)
                # Return location with original cleaned_name so display is consistent
                result.name = cleaned_name
                return result

        logger.debug("nominatim: no results for '%s' (tried %d queries)", cleaned_name, len(queries))
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def geocode(self, location_name: str) -> Optional[Location]:
        cleaned = self._clean_location_name(location_name)
        if not self._is_valid_location(cleaned):
            logger.info("geocoder: skipping invalid location '%s'", location_name)
            return None

        if self._use_mapbox:
            result = await self._geocode_mapbox(cleaned)
        elif self._use_google:
            result = await self._geocode_google(cleaned)
        else:
            async with _nominatim_lock:
                result = await self._geocode_nominatim(cleaned)
                await asyncio.sleep(_NOMINATIM_DELAY)

        if result:
            provider = "mapbox" if self._use_mapbox else "google" if self._use_google else "nominatim"
            logger.info("geocoder: '%s' → (%.4f, %.4f) [%s]",
                        cleaned, result.latitude, result.longitude, provider)
        else:
            logger.debug("geocoder: no result for '%s'", cleaned)
        return result

    async def geocode_multiple(self, location_names: list[str]) -> list[Location]:
        """Batch geocode; returns only successfully geocoded locations."""
        locations: list[Location] = []
        seen_coords: set[tuple[float, float]] = set()
        for name in location_names:
            result = await self.geocode(name)
            if result:
                coord_key = (round(result.latitude, 3), round(result.longitude, 3))
                if coord_key not in seen_coords:
                    seen_coords.add(coord_key)
                    locations.append(result)
        return locations

    async def geocode_many_preserve_names(
        self, location_names: list[str]
    ) -> list[tuple[str, Optional[Location]]]:
        """
        Geocode each name, returning (input_name, result_or_None) pairs.
        Mapbox/Google run concurrently; Nominatim stays sequential (1 req/s ToS).
        """
        if not location_names:
            return []
        if self._use_mapbox or self._use_google:
            results = await asyncio.gather(*[self.geocode(n) for n in location_names])
            return list(zip(location_names, results))
        out: list[tuple[str, Optional[Location]]] = []
        for name in location_names:
            out.append((name, await self.geocode(name)))
        return out

    # ------------------------------------------------------------------
    # Text extraction helpers (unchanged)
    # ------------------------------------------------------------------

    def _extract_locations_section(self, text: str) -> Optional[str]:
        patterns = [
            r"#{1,4}\s*📍\s*Locations?\s*:?\s*\n([\s\S]+?)(?=\n#{1,4}\s[^📍]|\n---|\Z)",
            r"#{1,4}\s*Locations?\s*:?\s*\n([\s\S]+?)(?=\n#{1,4}\s|\n---|\Z)",
            r"\*\*\s*📍?\s*Locations?\s*:?\s*\*\*\s*\n?([\s\S]+?)(?=\n\*\*|\n#{1,4}|\n---|\Z)",
            r"(?:^|\n)📍?\s*Locations?\s*:[ \t]*\n([\s\S]+?)(?=\n[A-Z][a-z]+:|\n#{1,4}|\n---|\Z)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content
        return None

    def _parse_location_lines(self, content: str) -> list[str]:
        locations: list[str] = []
        content_lower = content.lower().strip()
        for phrase in self.NO_LOCATION_PHRASES:
            if content_lower == phrase or content_lower.startswith(phrase):
                return []
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            if any(phrase in line.lower() for phrase in self.NO_LOCATION_PHRASES):
                continue
            line = re.sub(r'^[\s\-\*•►▸→·‣⁃\d\.\)]+\s*', '', line).strip()
            if not line:
                continue
            comma_count = line.count(',')
            if comma_count > 2:
                for part in line.split(','):
                    cleaned = self._clean_location_name(part)
                    if self._is_valid_location(cleaned):
                        locations.append(cleaned)
            elif ' and ' in line.lower() and comma_count == 0:
                for part in re.split(r'\s+and\s+', line, flags=re.IGNORECASE):
                    cleaned = self._clean_location_name(part)
                    if self._is_valid_location(cleaned):
                        locations.append(cleaned)
            else:
                cleaned = self._clean_location_name(line)
                if self._is_valid_location(cleaned):
                    locations.append(cleaned)
        return locations

    def extract_locations_from_text(self, text: str) -> list[str]:
        if not text:
            return []
        section = self._extract_locations_section(text)
        if not section:
            logger.debug("geocoder: no locations section in summary text")
            return []
        locations = self._parse_location_lines(section)
        if not locations:
            return []
        seen: set[str] = set()
        unique: list[str] = []
        for loc in locations:
            key = loc.lower()
            if key not in seen:
                seen.add(key)
                unique.append(loc)
        logger.info("geocoder: extracted %d location(s) from text", len(unique))
        return unique[:10]


# Singleton instance
geocoder = Geocoder()
