"""
Thin Altair wrappers so every chart in the app shares one look instead of
Vega-Lite's default per-call random categorical palette. Every chart here
is a single measure by category/time -- one sequential hue (blue, the
palette's primary) is the correct encoding, not a rainbow bar per category
(color would be encoding nothing; position already carries identity). See
the dataviz skill's color-formula: sequential = one hue for magnitude.
"""
import altair as alt

BLUE = "#2a78d6"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
MUTED = "#898781"

_BASE_CONFIG = {
    "axis": {
        "gridColor": GRID,
        "domainColor": AXIS,
        "tickColor": AXIS,
        "labelColor": MUTED,
        "titleColor": MUTED,
        "gridDash": [1, 0],  # solid, never dashed -- recessive hairline
    },
    "view": {"stroke": None},
}


def bar(df, x, y, x_title=None, y_title=None, height=320):
    chart = (
        alt.Chart(df)
        .mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=24)
        .encode(
            x=alt.X(f"{x}:N", title=x_title or x, sort="-y"),
            y=alt.Y(f"{y}:Q", title=y_title or y),
            tooltip=[x, y],
        )
        .properties(height=height)
        .configure(**_BASE_CONFIG)
    )
    return chart


def line(df, x, y, x_title=None, y_title=None, height=320):
    chart = (
        alt.Chart(df)
        .mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(color=BLUE, size=64, filled=True))
        .encode(
            x=alt.X(f"{x}:N", title=x_title or x),
            y=alt.Y(f"{y}:Q", title=y_title or y),
            tooltip=[x, y],
        )
        .properties(height=height)
        .configure(**_BASE_CONFIG)
    )
    return chart
