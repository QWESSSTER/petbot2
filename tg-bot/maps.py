import io
from staticmap import StaticMap, CircleMarker


def generate_map_image(locations: list) -> bytes | None:
    """
    Generates a PNG map image with locations marked.
    Green = unvisited, Blue = visited.
    locations rows: (id, list_id, added_by, added_by_name, name, category,
                     address, hours, avg_price, promotions, comment,
                     visited, rating, impression, latitude, longitude)
    Returns PNG bytes or None if no geocoded locations.
    """
    coords = [
        (row[15], row[14], bool(row[11]), row[4])  # lon, lat, visited, name
        for row in locations
        if row[14] is not None and row[15] is not None
    ]
    if not coords:
        return None

    m = StaticMap(800, 600, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png")

    for lon, lat, visited, name in coords:
        color = "#3B82F6" if visited else "#22C55E"
        marker = CircleMarker((lon, lat), color, 14)
        m.add_marker(marker)

    try:
        image = m.render()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
