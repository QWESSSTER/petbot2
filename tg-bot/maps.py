import folium
from folium.plugins import MarkerCluster
import io


def generate_folium_html(locations: list) -> str | None:
    """
    Generates a self-contained interactive Leaflet HTML map via Folium.
    Returns HTML string, or None if no geocoded locations exist.

    Row schema:
    id, list_id, added_by, added_by_name, name, category,
    address, hours, avg_price, promotions, comment,
    visited, rating, impression, latitude, longitude
    """
    geo_rows = [r for r in locations if r[14] is not None and r[15] is not None]
    if not geo_rows:
        return None

    # Center map on the average of all points
    avg_lat = sum(r[14] for r in geo_rows) / len(geo_rows)
    avg_lon = sum(r[15] for r in geo_rows) / len(geo_rows)

    m = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=13,
        tiles="OpenStreetMap",
    )

    cluster = MarkerCluster().add_to(m)

    for row in geo_rows:
        (loc_id, _, _, added_by_name, name, category,
         address, hours, avg_price, promotions, comment,
         visited, rating, impression, lat, lon) = row

        color = "blue" if visited else "green"
        icon_name = "check" if visited else "map-marker"

        stars = "⭐" * rating if rating else ""
        popup_lines = [f"<b style='font-size:14px'>{name}</b>"]
        if category:   popup_lines.append(f"<span style='color:#888'>{category}</span>")
        if address:    popup_lines.append(f"📍 {address}")
        if hours:      popup_lines.append(f"🕐 {hours}")
        if avg_price:  popup_lines.append(f"💰 {avg_price}")
        if stars:      popup_lines.append(f"Оценка: {stars}")
        if impression: popup_lines.append(f"<i>«{impression}»</i>")
        if visited:    popup_lines.append("<b style='color:green'>✅ Посещено</b>")

        popup_html = "<br>".join(popup_lines)

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=name,
            icon=folium.Icon(color=color, icon=icon_name, prefix="fa"),
        ).add_to(cluster)

    # Legend
    legend_html = """
    <div style="
        position: fixed; bottom: 30px; left: 30px; z-index: 1000;
        background: white; padding: 10px 14px; border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3); font-family: sans-serif; font-size: 13px;
    ">
        <b>Легенда</b><br>
        <span style="color:#3186cc">&#9679;</span> Хочу посетить<br>
        <span style="color:#6a9f4b">&#9679;</span> Уже был
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m.get_root().render()
