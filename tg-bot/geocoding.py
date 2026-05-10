import asyncio
from functools import partial
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

_geolocator = Nominatim(user_agent="wishlist_bot_v1", timeout=5)


async def geocode_address(address: str) -> tuple[float, float] | None:
    """Returns (lat, lon) or None if not found."""
    if not address:
        return None
    try:
        loop = asyncio.get_event_loop()
        location = await loop.run_in_executor(
            None, partial(_geolocator.geocode, address, language="ru")
        )
        if location:
            return location.latitude, location.longitude
    except (GeocoderTimedOut, Exception):
        pass
    return None
