"""
Geocoding service using Google Cloud Geocoding API
"""
import asyncio
import re
from typing import Optional, Dict, Any, List, Tuple
import httpx

from config import GOOGLE_MAPS_API_KEY


class GeocodingError(Exception):
    """Custom exception for geocoding errors"""
    pass


class Location:
    """Represents a location with coordinates"""
    def __init__(self, name: str, latitude: float, longitude: float, display_name: str = ""):
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.display_name = display_name
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "display_name": self.display_name,
        }


class Geocoder:
    """Service for geocoding locations using Google Cloud Geocoding API"""
    
    BASE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    
    # Phrases that indicate no locations were found
    NO_LOCATION_PHRASES = [
        'none mentioned', 'none', 'n/a', 'not mentioned', 
        'no specific', 'no locations', 'not specified',
        'none were mentioned', 'no places', 'not applicable',
        'no location', 'unidentified', 'unknown location',
        'no geographical', 'not identifiable', 'indoors',
        'indoor setting', 'studio', 'unspecified'
    ]
    
    # Words/phrases to skip (not actual locations)
    SKIP_PHRASES = [
        'the video', 'this video', 'the reel', 'various', 
        'multiple locations', 'several places', 'different areas',
        'background', 'setting', 'scene', 'shot', 'frame',
        'mentioned', 'shown', 'visible', 'appears', 'featured'
    ]
    
    # Common descriptors to remove from location names
    DESCRIPTORS_TO_REMOVE = [
        r'\(.*?\)',  # Remove parenthetical content
        r'\[.*?\]',  # Remove bracketed content
        r'(?:^|\s)(?:the|a|an)\s+',  # Remove articles
        r'(?:\s*[-–—]\s*.+)$',  # Remove dash-suffixed descriptions
        r'(?:,\s*(?:which|where|that|a|the)\s+.+)$',  # Remove trailing clauses
    ]
    
    def __init__(self):
        self.api_key = GOOGLE_MAPS_API_KEY
        if not self.api_key:
            print("⚠️ Warning: GOOGLE_MAPS_API_KEY not set. Geocoding will not work.")
    
    def _clean_location_name(self, name: str) -> str:
        """Clean and normalize a location name for better geocoding."""
        cleaned = name.strip()
        
        # Remove common prefixes
        cleaned = re.sub(r'^(?:at|in|near|around|from|to)\s+', '', cleaned, flags=re.IGNORECASE)
        
        # Remove descriptors
        for pattern in self.DESCRIPTORS_TO_REMOVE:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Remove quotes
        cleaned = cleaned.strip('"\'""''')
        
        # Remove trailing punctuation
        cleaned = cleaned.rstrip('.,;:!?')
        
        # Normalize whitespace
        cleaned = ' '.join(cleaned.split())
        
        return cleaned.strip()
    
    def _is_valid_location(self, name: str) -> bool:
        """Check if the extracted text is likely a valid location."""
        name_lower = name.lower()
        
        # Too short or too long
        if len(name) < 2 or len(name) > 100:
            return False
        
        # Contains skip phrases
        if any(phrase in name_lower for phrase in self.SKIP_PHRASES):
            return False
        
        # Is a "no location" phrase
        if any(phrase in name_lower for phrase in self.NO_LOCATION_PHRASES):
            return False
        
        # Has mostly numbers (not a place name)
        if sum(c.isdigit() for c in name) > len(name) / 2:
            return False
        
        # Has no letters
        if not any(c.isalpha() for c in name):
            return False
        
        # Looks like a sentence (too many words without proper noun structure)
        words = name.split()
        if len(words) > 6:
            return False
        
        return True
    
    async def geocode(self, location_name: str) -> Optional[Location]:
        """
        Get coordinates for a location name using Google Cloud Geocoding API.
        
        Args:
            location_name: The name of the location to geocode
            
        Returns:
            Location object with coordinates, or None if not found
        """
        if not self.api_key:
            print(f"⚠️ Cannot geocode '{location_name}': API key not configured")
            return None
        
        # Clean the location name first
        cleaned_name = self._clean_location_name(location_name)
        
        if not self._is_valid_location(cleaned_name):
            print(f"⚠️ Skipping invalid location: '{location_name}'")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "address": cleaned_name,
                        "key": self.api_key,
                    },
                    timeout=10.0,
                )
                
                if response.status_code != 200:
                    print(f"⚠️ Geocoding failed for '{cleaned_name}': HTTP {response.status_code}")
                    return None
                
                data = response.json()
                
                # Check API response status
                status = data.get("status", "")
                if status != "OK":
                    if status == "ZERO_RESULTS":
                        print(f"⚠️ No results found for location: '{cleaned_name}'")
                    elif status == "REQUEST_DENIED":
                        print(f"❌ Geocoding request denied. Check your API key.")
                    elif status == "OVER_QUERY_LIMIT":
                        print(f"⚠️ Geocoding quota exceeded.")
                    else:
                        print(f"⚠️ Geocoding failed for '{cleaned_name}': {status}")
                    return None
                
                results = data.get("results", [])
                if not results:
                    print(f"⚠️ No results found for location: '{cleaned_name}'")
                    return None
                
                result = results[0]
                geometry = result.get("geometry", {})
                location_data = geometry.get("location", {})
                
                lat = location_data.get("lat")
                lng = location_data.get("lng")
                
                if lat is None or lng is None:
                    print(f"⚠️ Invalid coordinates for location: '{cleaned_name}'")
                    return None
                
                return Location(
                    name=cleaned_name,
                    latitude=float(lat),
                    longitude=float(lng),
                    display_name=result.get("formatted_address", cleaned_name),
                )
                
        except Exception as e:
            print(f"❌ Error geocoding '{cleaned_name}': {e}")
            return None
    
    async def geocode_multiple(self, location_names: List[str]) -> List[Location]:
        """
        Get coordinates for multiple locations using Google Cloud Geocoding API.
        
        Args:
            location_names: List of location names to geocode
            
        Returns:
            List of Location objects (only successful geocodes)
        """
        if not self.api_key:
            print("⚠️ Cannot geocode: GOOGLE_MAPS_API_KEY not configured")
            return []
        
        locations = []
        seen_coords: set[Tuple[float, float]] = set()
        
        for name in location_names:
            # Small delay to avoid hitting rate limits (Google allows 50 QPS)
            if locations:
                await asyncio.sleep(0.1)  # 100ms delay between requests
            
            location = await self.geocode(name)
            if location:
                # Avoid duplicate coordinates (same place with different names)
                coord_key = (round(location.latitude, 3), round(location.longitude, 3))
                if coord_key not in seen_coords:
                    seen_coords.add(coord_key)
                    locations.append(location)
                    print(f"📍 Geocoded '{name}': ({location.latitude}, {location.longitude})")
                else:
                    print(f"📍 Skipping duplicate location: '{name}'")
        
        return locations
    
    def _extract_locations_section(self, text: str) -> Optional[str]:
        """Extract the locations section content from the summary."""
        # Multiple patterns to try, from most specific to least
        patterns = [
            # With emoji: ### 📍 Locations:
            r"#{1,4}\s*📍\s*Locations?\s*:?\s*\n([\s\S]+?)(?=\n#{1,4}\s[^📍]|\n---|\Z)",
            # Without emoji: ### Locations:
            r"#{1,4}\s*Locations?\s*:?\s*\n([\s\S]+?)(?=\n#{1,4}\s|\n---|\Z)",
            # Bold format: **Locations:**
            r"\*\*\s*📍?\s*Locations?\s*:?\s*\*\*\s*\n?([\s\S]+?)(?=\n\*\*|\n#{1,4}|\n---|\Z)",
            # Simple format: Locations:
            r"(?:^|\n)📍?\s*Locations?\s*:[ \t]*\n([\s\S]+?)(?=\n[A-Z][a-z]+:|\n#{1,4}|\n---|\Z)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content
        
        return None
    
    def _parse_location_lines(self, content: str) -> List[str]:
        """Parse individual locations from the section content."""
        locations = []
        
        # Check if the entire content indicates no locations
        content_lower = content.lower().strip()
        for phrase in self.NO_LOCATION_PHRASES:
            if content_lower == phrase or content_lower.startswith(phrase):
                return []
        
        # Split into lines
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if this line indicates no locations
            line_lower = line.lower()
            if any(phrase in line_lower for phrase in self.NO_LOCATION_PHRASES):
                continue
            
            # Remove bullet points, dashes, asterisks, numbers at start
            line = re.sub(r'^[\s\-\*•►▸→·‣⁃\d\.\)]+\s*', '', line).strip()
            
            if not line:
                continue
            
            # Check if line has multiple locations (comma-separated, NOT part of "City, Country" format)
            # Only split if there are more than 2 commas (suggesting list, not just city+country)
            comma_count = line.count(',')
            
            if comma_count > 2:
                # Likely a list: "Paris, New York, Tokyo"
                parts = [p.strip() for p in line.split(',')]
                for part in parts:
                    cleaned = self._clean_location_name(part)
                    if self._is_valid_location(cleaned):
                        locations.append(cleaned)
            elif ' and ' in line.lower() and comma_count == 0:
                # "Paris and London" pattern
                parts = re.split(r'\s+and\s+', line, flags=re.IGNORECASE)
                for part in parts:
                    cleaned = self._clean_location_name(part)
                    if self._is_valid_location(cleaned):
                        locations.append(cleaned)
            else:
                # Single location (possibly "City, Country" format)
                cleaned = self._clean_location_name(line)
                if self._is_valid_location(cleaned):
                    locations.append(cleaned)
        
        return locations
    
    def extract_locations_from_text(self, text: str) -> List[str]:
        """
        Extract location names from LLM-generated summary text.
        Looks for the specific header format: ### 📍 Locations:
        
        Args:
            text: The summary text to extract locations from
            
        Returns:
            List of unique location names found (max 10)
        """
        if not text:
            return []
        
        # Extract the locations section
        section_content = self._extract_locations_section(text)
        
        if not section_content:
            print("📍 No locations header found in summary")
            return []
        
        print(f"📍 Found locations section: {section_content[:100]}...")
        
        # Parse locations from the section
        locations = self._parse_location_lines(section_content)
        
        if not locations:
            print("📍 No valid locations found in section")
            return []
        
        # Remove duplicates while preserving order
        seen = set()
        unique_locations = []
        for loc in locations:
            loc_lower = loc.lower()
            if loc_lower not in seen:
                seen.add(loc_lower)
                unique_locations.append(loc)
        
        print(f"📍 Extracted {len(unique_locations)} unique locations: {unique_locations}")
        
        return unique_locations[:10]  # Limit to 10 locations


# Singleton instance
geocoder = Geocoder()

