"""Provides shared constants for team labels, element-type ordering, and color
palettes.
"""

# We treat these `created_by` prefixes as survey-app submissions, so we can
# distinguish them from the initial TDEI workspace import or edits made via
# Rapid.
APP_CREATED_BY_PREFIXES = ("AVIV ScoutRoute", "GIG", "GoInfoGame")

TEAM_LABELS = {
    "connecting_to_transit": "Connecting to Transit",
    "access_pathways": "Access Pathways",
    "bus_stop_management": "Bus Stop Management",
    "bus_stop_improvements": "Bus Stop Improvements",
    "ada_transition_plan": "ADA Transition Plan",
    "speed_and_reliability": "Speed & Reliability",
    "transit_route_facilities": "Transit Route Facilities",
    "internal_metro_note": "Internal Metro Note",
}

MODIFY_KIND_LABELS = {
    "geometry_only": "Geometry only",
    "tags_only": "Tags only",
    "both": "Geometry + tags",
    "no_op": "No-op edit",
}

ELEMENT_TYPE_ORDER = ["Sidewalks", "Crossings", "Bus Stops", "Curbs", "Intersections"]

ELEMENT_TYPE_COLORS = {
    "Sidewalks":     "#0d6efd",
    "Crossings":     "#fd7e14",
    "Bus Stops":     "#198754",
    "Curbs":         "#e83e8c",  # pink--we reserve #dc3545 for hotspot beacons
    "Intersections": "#6f42c1",
    "Street Lamps":  "#ffc107",
}
"""Shared constants: colour palettes, element-type ordering, team labels."""

# We identify survey-app submissions by these `created_by` prefixes, which
# distinguishes them from TDEI workspace imports or edits made via Rapid.
APP_CREATED_BY_PREFIXES = ("AVIV ScoutRoute", "GIG", "GoInfoGame")

TEAM_LABELS = {
    "connecting_to_transit": "Connecting to Transit",
    "access_pathways": "Access Pathways",
    "bus_stop_management": "Bus Stop Management",
    "bus_stop_improvements": "Bus Stop Improvements",
    "ada_transition_plan": "ADA Transition Plan",
    "speed_and_reliability": "Speed & Reliability",
    "transit_route_facilities": "Transit Route Facilities",
    "internal_metro_note": "Internal Metro Note",
}

MODIFY_KIND_LABELS = {
    "geometry_only": "Geometry only",
    "tags_only": "Tags only",
    "both": "Geometry + tags",
    "no_op": "No-op edit",
}

ELEMENT_TYPE_ORDER = ["Sidewalks", "Crossings", "Bus Stops", "Curbs", "Intersections"]

ELEMENT_TYPE_COLORS = {
    "Sidewalks":     "#0d6efd",
    "Crossings":     "#fd7e14",
    "Bus Stops":     "#198754",
    "Curbs":         "#e83e8c",  # pink--we reserve #dc3545 for hotspot beacons
    "Intersections": "#6f42c1",
    "Street Lamps":  "#ffc107",
}

KARTAVIEW_CDN_PREFIX = "https://cdn.kartaview.org/pr:sharp/"


# ---------------------------------------------------------------------------
# Scoring in issues.py employs this diverging severity ramp, which maps a score
# of -1 to the worst problem, 0 to neutral, and +1 to the best.
# ---------------------------------------------------------------------------

# We define each stop as a tuple containing a score and an RGB color.
_SEVERITY_RAMP = [
    (-1.0, (220, 53,  69)),  # danger red from Bootstrap (#dc3545)
    (-0.5, (253, 126, 20)),   # Bootstrap orange        #fd7e14
    ( 0.0, (255, 193,  7)),   # Bootstrap yellow        #ffc107
    ( 0.5, (100, 173, 80)),   # mid green               #64ad50
    ( 1.0, ( 25, 135, 84)),  # Bootstrap success green (#198754)
]

SEVERITY_SIGN_THRESHOLD = 0.1  # |score| < threshold is neutral

# ---------------------------------------------------------------------------
# Issue dimension system
# ---------------------------------------------------------------------------

# Pedestrian infrastructure quality depends on three orthogonal dimensions. We
# classify each note and quest tag into at least one of these categories.
DIMENSIONS = ("traversability", "connectivity", "safety_comfort")

DIMENSION_LABELS = {
    "traversability": "Traversability",
    "connectivity":   "Connectivity",
    "safety_comfort": "Safety & Comfort",
}

# We use these weights to roll up each dimension into a combined score.
#
# Because safety_comfort provides informative data but has less impact on how
# we rank issues, we assign it a lower weight.
DIMENSION_WEIGHTS = {
    "traversability": 1.0,
    "connectivity":   1.0,
    "safety_comfort": 0.5,
}

# We cap full quantity at 3 corroborating voices since block-by-block surveys
# seldom find more than ~3 people per location. The confidence "quantity"
# sub-factor saturates at this number of distinct contributors (independent
# voices) instead of an unreachable 10.
QUANTITY_TARGET_VOICES = 3

# We propagate a fraction of the barrier's `conn_score` across exactly one hop.
CONNECTIVITY_DECAY = 0.5



def text_on_color(hex_color: str) -> str:
    """Returns '#fff' or '#212529' to maximize contrast against *hex_color*.

    We determine this by applying a relative-luminance threshold based on the
    W3C formula (approx γ = 2.2). We accept '#rrggbb' strings like those
    returned by `diverging_color()`.
    """
    h = hex_color.lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return "#212529"
    # We linearize sRGB before calculating luminance.
    def lin(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#fff" if lum < 0.35 else "#212529"


def diverging_color(score: float) -> str:
    """Maps a signed score between -1 and +1 to a hex color from a
    red->yellow->green ramp.
    """
    score = max(-1.0, min(1.0, float(score)))
    for i in range(len(_SEVERITY_RAMP) - 1):
        lo_s, lo_rgb = _SEVERITY_RAMP[i]
        hi_s, hi_rgb = _SEVERITY_RAMP[i + 1]
        if score <= hi_s:
            t = (score - lo_s) / (hi_s - lo_s)
            r = round(lo_rgb[0] + (hi_rgb[0] - lo_rgb[0]) * t)
            g = round(lo_rgb[1] + (hi_rgb[1] - lo_rgb[1]) * t)
            b = round(lo_rgb[2] + (hi_rgb[2] - lo_rgb[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    _, rgb = _SEVERITY_RAMP[-1]
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
