"""Generate the Power BI project (PBIP) from code: a TMDL semantic model + a PBIR report.

Everything in the dashboard is defined here: tables, relationships, DAX measures, pages and visuals.
Column types are read from the Parquet files in data/serving/, so the model always matches the pipeline.

Usage:
    python dashboard/build_pbip.py            # writes dashboard/MarketingAnalytics.{pbip,SemanticModel,Report}
    python dashboard/build_pbip.py --validate # also validates every report JSON file against Microsoft's schemas

Open dashboard/MarketingAnalytics.pbip in Power BI Desktop, then Home > Refresh to load the data.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PBI_DIR = ROOT / "dashboard"
SERVING = ROOT / "data" / "serving"
NAME = "MarketingAnalytics"
SM_DIR = PBI_DIR / f"{NAME}.SemanticModel"
RP_DIR = PBI_DIR / f"{NAME}.Report"
DARK_DIR = PBI_DIR / f"{NAME}Dark.Report"
NS = uuid.UUID("6b1c3f0e-7a52-4c1e-9a55-3f0d2b8e9c11")  # fixed namespace -> stable lineage tags across rebuilds

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VISUAL_SCHEMA = f"{SCHEMA}/item/report/definition/visualContainer/2.7.0/schema.json"
PAGE_SCHEMA = f"{SCHEMA}/item/report/definition/page/2.0.0/schema.json"

# Design tokens: design/tokens.json (docs/design_system.md). The light theme file is generated from them too.
TOKENS = json.loads((ROOT / "design" / "tokens.json").read_text(encoding="utf-8"))
_T = TOKENS["color"]
PRIMARY = _T["data.primary"]              # the data
PRIMARY_STRONG = _T["data.primary.strong"]
SECONDARY = _T["data.secondary"]
CONTEXT = _T["data.comparison"]           # comparison / everything else
ACCENT = _T["data.highlight"]             # the one thing to look at, against grey context
ACCENT_TEXT = _T["data.highlight.text"]
POSITIVE, NEGATIVE = _T["status.positive.text"], _T["status.negative.text"]
INK, INK_2, MUTED = _T["text.primary"], _T["text.secondary"], _T["text.muted"]
BORDER = _T["border.subtle"]
HEAT_MIN, HEAT_MAX = _T["sequential.low"], _T["sequential.high"]
CARD = _T["background.primary"]           # visual container background
PAGE_BG = _T["background.secondary"]
SELECTED = _T["background.selected"]      # decision strip panels
SIDE_BG, SIDE_TEXT, SIDE_MUTED = _T["sidebar.background"], _T["sidebar.text"], _T["sidebar.muted"]
SIDE_SELECTED, SIDE_SELECTED_TEXT = _T["sidebar.selected"], _T["sidebar.selected.text"]
KPI_ACCENTS = _T["kpi.accents"]           # thin colour bar on top of each KPI card
SEMIBOLD = "'''Segoe UI Semibold'', wf_segoe-ui_semibold, helvetica, arial, sans-serif'"
REGULAR = "'''Segoe UI'', wf_segoe-ui_normal, helvetica, arial, sans-serif'"
BRAND = TOKENS["name"]
INDEPENDENCE = TOKENS["independence_note"]

# Grid: 1440x900 canvas, 224px sidebar, content from x=240: 12 columns x 84px, 16px gutters (8px base unit)
MARGIN, COL_W, GUTTER, SIDE_W = 240, 84, 16, 224
BAND = {"header": (16, 56), "kpi": (84, 104), "primary": (204, 296), "support": (516, 264),
        "decision": (796, 68), "footer": (872, 20)}


DARK_PALETTE = {  # "Night" variant (dashboard/theme_dark.json); every text colour >= 5:1 on CARD
    "PRIMARY": "#9C88FF", "CONTEXT": "#6E6990", "ACCENT": "#F472B6", "ACCENT_TEXT": "#F472B6",
    "POSITIVE": "#4ADE80", "NEGATIVE": "#FF7A90", "INK": "#F5F4FA", "INK_2": "#B8B3D1", "MUTED": "#9893B5",
    "BORDER": "#3A355C", "HEAT_MIN": "#2E2A4C", "HEAT_MAX": "#7C6AE6", "CARD": "#262241",
}
TEAL, TRACK, SIDEBAR = "#4FD1E0", "#38335A", "#1F1B35"


class palette:
    """Temporarily swap the module colour tokens (so the same helpers render light or dark)."""

    def __init__(self, overrides: dict):
        self.overrides, self.saved = overrides, {}

    def __enter__(self):
        g = globals()
        self.saved = {k: g[k] for k in self.overrides}
        g.update(self.overrides)

    def __exit__(self, *exc):
        globals().update(self.saved)


def gx(col: int) -> int:
    """x position of a grid column (0-11)."""
    return MARGIN + col * (COL_W + GUTTER)


def gw(span: int) -> int:
    """width of a span of grid columns."""
    return span * COL_W + (span - 1) * GUTTER


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL object name when needed."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


# =====================================================================================
# SEMANTIC MODEL
# =====================================================================================

@dataclass
class TableSpec:
    hidden: tuple[str, ...] = ()
    sort_by: dict | None = None
    formats: dict | None = None
    is_date_table: bool = False
    data_categories: dict | None = None  # geocoding hints for map visuals


TABLES: dict[str, TableSpec] = {
    "fct_sessions": TableSpec(hidden=("session_key", "user_pseudo_id", "session_date", "session_channel_group",
                                      "device_category"),
                            data_categories={"geo_country": "Country", "geo_city": "City"}),
    "fct_orders": TableSpec(sort_by={"order_value_band": "order_value_band_sort"}, hidden=("order_value_band_sort", "order_id", "session_key", "user_pseudo_id", "order_date",
                                    "session_channel_group", "device_category")),
    "fct_attribution_credits": TableSpec(hidden=("order_id", "session_key", "order_date", "channel", "model")),
    "attribution_markov": TableSpec(hidden=("channel", "model")),
    "dim_date": TableSpec(hidden=("month_sort", "day_of_week_num"), is_date_table=True,
                          sort_by={"month_label": "month_sort", "day_name": "day_of_week_num"},
                          formats={"date": "dd mmm yyyy", "week_start": "dd mmm yyyy"}),
    "dim_channel": TableSpec(hidden=("sort_order",), sort_by={"channel": "sort_order"}),
    "dim_device": TableSpec(hidden=("sort_order",), sort_by={"device_category": "sort_order"}),
    "dim_funnel_stage": TableSpec(hidden=("stage_order",), sort_by={"stage_name": "stage_order"}),
    "dim_attribution_model": TableSpec(hidden=("sort_order", "model"), sort_by={"model_label": "sort_order"}),
    "fct_order_items": TableSpec(hidden=("order_id", "order_date", "session_key")),
    "mart_product_pairs": TableSpec(),
    "dim_customers": TableSpec(hidden=("user_pseudo_id", "first_order_date", "cohort_month", "acquisition_channel",
                                       "first_device", "repeat_window_sort"),
                               sort_by={"repeat_window": "repeat_window_sort"},
                               data_categories={"country": "Country"}),
}

RELATIONSHIPS = [  # (many side, one side)
    ("fct_sessions", "session_date", "dim_date", "date"),
    ("fct_sessions", "session_channel_group", "dim_channel", "channel"),
    ("fct_sessions", "device_category", "dim_device", "device_category"),
    ("fct_orders", "order_date", "dim_date", "date"),
    ("fct_orders", "session_channel_group", "dim_channel", "channel"),
    ("fct_orders", "device_category", "dim_device", "device_category"),
    ("fct_attribution_credits", "order_date", "dim_date", "date"),
    ("fct_attribution_credits", "channel", "dim_channel", "channel"),
    ("fct_attribution_credits", "model", "dim_attribution_model", "model"),
    ("attribution_markov", "channel", "dim_channel", "channel"),
    ("fct_order_items", "order_date", "dim_date", "date"),
    ("dim_customers", "first_order_date", "dim_date", "date"),          # customers filter by first purchase
    ("dim_customers", "acquisition_channel", "dim_channel", "channel"),
    ("dim_customers", "first_device", "dim_device", "device_category"),
]

DUCK_TO_TMDL = {"VARCHAR": "string", "BIGINT": "int64", "INTEGER": "int64", "DOUBLE": "double",
                "DATE": "dateTime", "TIMESTAMP": "dateTime", "BOOLEAN": "boolean", "FLOAT": "double"}

# ---- measures: (name, display folder, format string, DAX) -------------------------------------------

WHOLE, PCT1, PCT2 = "#,0", "0.0%", "0.00%"
CUR0, CUR2 = r"\$#,0", r"\$#,0.00"


def prev_period(base: str) -> str:
    return f"""VAR _start = MIN ( dim_date[date] )
VAR _days = INT ( MAX ( dim_date[date] ) - _start ) + 1
RETURN
    CALCULATE ( [{base}], DATESBETWEEN ( dim_date[date], _start - _days, _start - 1 ) )"""


def change_label(base: str, is_rate: bool = False) -> str:
    change = ('FORMAT ( ABS ( _cur - _pp ) * 100, "0.00" ) & " pts"' if is_rate
              else 'FORMAT ( ABS ( DIVIDE ( _cur - _pp, _pp ) ), "0.0%" )')
    return f"""VAR _cur = [{base}]
VAR _pp = [{base} PP]
RETURN
    IF (
        ISBLANK ( _pp ),
        "No prior period",
        IF ( _cur >= _pp, "▲ ", "▼ " ) & {change} & " vs previous period"
    )"""


def reached(flag: str) -> str:
    return f"CALCULATE ( [Sessions], fct_sessions[{flag}] = TRUE () )"


def reached_clean(flag: str | None = None) -> str:
    """Funnel counts only use days when the add_to_cart tag worked (22 November days excluded)."""
    extra = f", fct_sessions[{flag}] = TRUE ()" if flag else ""
    return f"CALCULATE ( [Sessions]{extra}, dim_date[is_cart_tracking_ok] = TRUE () )"


def change_color(base: str, pos: str = POSITIVE, neg: str = NEGATIVE, muted: str = MUTED) -> str:
    """Text colour for a KPI comparison: green up, red down, muted when there's nothing to compare."""
    return f"""VAR _cur = [{base}]
VAR _pp = [{base} PP]
RETURN
    IF ( ISBLANK ( _pp ), "{muted}", IF ( _cur >= _pp, "{pos}", "{neg}" ) )"""


def highlight(column: str, value: str, accent: str = ACCENT, base: str = CONTEXT) -> str:
    """Bar colour measure: the accent for one category, context grey for the rest."""
    return f'IF ( SELECTEDVALUE ( {column} ) = "{value}", "{accent}", "{base}" )'


KPI_BASES = ["Revenue", "Orders", "Conversion Rate", "AOV", "Revenue per Session", "Sessions", "Users", "Engagement Rate",
             "New User %", "Session to View Rate", "View to Cart Rate", "Cart to Checkout Rate",
             "Checkout to Purchase Rate"]
RATE_KPIS = {"Conversion Rate", "Engagement Rate", "New User %", "Session to View Rate", "View to Cart Rate",
             "Cart to Checkout Rate", "Checkout to Purchase Rate"}


MEASURES: list[tuple[str, str, str | None, str]] = [
    # Traffic
    ("Sessions", "Traffic", WHOLE, "COUNTROWS ( fct_sessions )"),
    ("Users", "Traffic", WHOLE, "DISTINCTCOUNT ( fct_sessions[user_pseudo_id] )"),
    ("Engaged Sessions", "Traffic", WHOLE, reached("is_engaged")),
    ("Engagement Rate", "Traffic", PCT1, "DIVIDE ( [Engaged Sessions], [Sessions] )"),
    ("New User %", "Traffic", PCT1, f"DIVIDE ( {reached('is_new_user_session')}, [Sessions] )"),
    # Sales: one row per deduplicated order (by transaction_id, or session + amount + basket when the ID is missing)
    ("Orders", "Sales", WHOLE, "COUNTROWS ( fct_orders )"),
    ("Revenue", "Sales", CUR0, "SUM ( fct_orders[purchase_revenue_usd] )"),
    ("Conversion Rate", "Sales", PCT2, "DIVIDE ( [Orders], [Sessions] )"),
    ("AOV", "Sales", CUR2, "DIVIDE ( [Revenue], [Orders] )"),
    ("Revenue per Session", "Sales", CUR2, "DIVIDE ( [Revenue], [Sessions] )"),
    # Funnel
    ("Funnel Base Sessions", "Funnel", WHOLE, reached_clean()),
    ("Sessions Viewed Product", "Funnel", WHOLE, reached_clean("reached_view_item")),
    ("Sessions Added to Cart", "Funnel", WHOLE, reached_clean("reached_add_to_cart")),
    ("Sessions Began Checkout", "Funnel", WHOLE, reached_clean("reached_begin_checkout")),
    ("Sessions Purchased", "Funnel", WHOLE, reached_clean("reached_purchase")),
    ("Funnel Sessions", "Funnel", WHOLE, """SWITCH (
    SELECTEDVALUE ( dim_funnel_stage[stage_order] ),
    1, [Funnel Base Sessions],
    2, [Sessions Viewed Product],
    3, [Sessions Added to Cart],
    4, [Sessions Began Checkout],
    5, [Sessions Purchased]
)"""),
    # REMOVEFILTERS matters: visuals filter stage_name (sorted by stage_order), so a plain
    # stage_order = 1 filter would be ANDed with the current stage name and return blank.
    ("Funnel % of Sessions", "Funnel", PCT1, """DIVIDE (
    [Funnel Sessions],
    CALCULATE ( [Funnel Sessions], REMOVEFILTERS ( dim_funnel_stage ), dim_funnel_stage[stage_order] = 1 )
)"""),
    ("Funnel Step Rate", "Funnel", PCT1, """VAR _stage = SELECTEDVALUE ( dim_funnel_stage[stage_order] )
RETURN
    IF (
        _stage > 1,
        DIVIDE (
            [Funnel Sessions],
            CALCULATE ( [Funnel Sessions], REMOVEFILTERS ( dim_funnel_stage ), dim_funnel_stage[stage_order] = _stage - 1 )
        )
    )"""),
    ("Session to View Rate", "Funnel", PCT1, "DIVIDE ( [Sessions Viewed Product], [Funnel Base Sessions] )"),
    ("View to Cart Rate", "Funnel", PCT1, "DIVIDE ( [Sessions Added to Cart], [Sessions Viewed Product] )"),
    ("Cart to Checkout Rate", "Funnel", PCT1, "DIVIDE ( [Sessions Began Checkout], [Sessions Added to Cart] )"),
    ("Checkout to Purchase Rate", "Funnel", PCT1, "DIVIDE ( [Sessions Purchased], [Sessions Began Checkout] )"),
    # Attribution (rule-based: date-aware; Markov: channel-level over the full period)
    ("Attributed Conversions", "Attribution", WHOLE, """VAR _model = SELECTEDVALUE ( dim_attribution_model[model], "last_click" )
RETURN
    IF (
        _model = "markov",
        SUM ( attribution_markov[conversions] ),
        CALCULATE ( SUM ( fct_attribution_credits[credit] ), dim_attribution_model[model] = _model )
    )"""),
    ("Attributed Revenue", "Attribution", CUR0, """VAR _model = SELECTEDVALUE ( dim_attribution_model[model], "last_click" )
RETURN
    IF (
        _model = "markov",
        SUM ( attribution_markov[revenue_usd] ),
        CALCULATE ( SUM ( fct_attribution_credits[revenue_credit_usd] ), dim_attribution_model[model] = _model )
    )"""),
    ("Attributed Share", "Attribution", PCT1,
     "DIVIDE ( [Attributed Conversions], CALCULATE ( [Attributed Conversions], ALL ( dim_channel ) ) )"),
    ("Orders (Naive Last Click)", "Attribution", WHOLE, "[Orders]"),
    ("Orders (Corrected Last Click)", "Attribution", WHOLE,
     'CALCULATE ( SUM ( fct_attribution_credits[credit] ), dim_attribution_model[model] = "last_click" )'),
    ("Self-Referral Correction", "Attribution", "+#,0;-#,0;0",
     "[Orders (Corrected Last Click)] - [Orders (Naive Last Click)]"),
    ("Markov Share", "Attribution", PCT1, "SUM ( attribution_markov[share] )"),
    ("Markov Share CI Low", "Attribution", PCT1, "SUM ( attribution_markov[share_ci_low] )"),
    ("Markov Share CI High", "Attribution", PCT1, "SUM ( attribution_markov[share_ci_high] )"),
    ("Markov Conversions", "Attribution", WHOLE, "SUM ( attribution_markov[conversions] )"),
    ("Markov vs Last Click", "Attribution", "+0%;-0%;0%",
     "DIVIDE ( [Markov Conversions] - [Orders (Corrected Last Click)], [Orders (Corrected Last Click)] )"),
    ("Markov 95% CI", "Attribution", None,
     'IF ( NOT ISBLANK ( [Markov Share] ), FORMAT ( [Markov Share CI Low], "0.0%" ) & " to " '
     '& FORMAT ( [Markov Share CI High], "0.0%" ) )'),
    ("Self-Referral Orders", "Attribution", WHOLE, 'CALCULATE ( [Orders], dim_channel[channel] = "Internal Referral" )'),
    ("Self-Referral Share", "Attribution", PCT1, "DIVIDE ( [Self-Referral Orders], [Orders] )"),
    ("Organic Search Markov Share", "Attribution", PCT1,
     'CALCULATE ( [Markov Share], dim_channel[channel] = "Organic Search" )'),
    ("Paid Search Markov Uplift", "Attribution", "+0%;-0%;0%",
     'CALCULATE ( [Markov vs Last Click], dim_channel[channel] = "Paid Search" )'),
    # Customers: one row per browser with an order; date, channel and device filters apply to the FIRST purchase
    ("Customers", "Customers", WHOLE, "COUNTROWS ( dim_customers )"),
    ("Repeat Customer Rate", "Customers", PCT1,
     "DIVIDE ( CALCULATE ( [Customers], dim_customers[buying_days] >= 2 ), [Customers] )"),
    ("Median Customer Spend", "Customers", CUR0, "MEDIAN ( dim_customers[revenue_usd] )"),
    ("Average Customer Spend", "Customers", CUR0, "AVERAGE ( dim_customers[revenue_usd] )"),
    ("Customer Revenue", "Customers", CUR0, "SUM ( dim_customers[revenue_usd] )"),
    ("Share of Customers", "Customers", PCT1,
     "DIVIDE ( [Customers], CALCULATE ( [Customers], REMOVEFILTERS ( dim_customers[rfm_segment] ) ) )"),
    ("Share of Revenue", "Customers", PCT1,
     "DIVIDE ( [Customer Revenue], CALCULATE ( [Customer Revenue], REMOVEFILTERS ( dim_customers[rfm_segment] ) ) )"),
    ("Big Spender Revenue Share", "Customers", PCT1,
     'CALCULATE ( [Share of Revenue], dim_customers[rfm_segment] = "Big one-off spenders" )'),
    ("Repeat Buyers", "Customers", WHOLE, "CALCULATE ( [Customers], dim_customers[buying_days] >= 2 )"),
    ("Back Within 14 Days", "Customers", PCT1,
     "DIVIDE ( CALCULATE ( [Repeat Buyers], dim_customers[days_to_repeat] <= 14 ), [Repeat Buyers] )"),
    # Only customers who could be followed for the whole window (data ends 31 Jan), and only with 100+ of them.
    # Repeat Buyers, not Customers, in the numerator: a blank days_to_repeat would pass "<= N" in DAX.
    ("Repeat Within 7 Days", "Customers", PCT1, """VAR _cut = DATE ( 2021, 1, 31 ) - 7
VAR _eligible = CALCULATE ( [Customers], KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) )
RETURN
    IF (
        _eligible >= 100,
        DIVIDE (
            CALCULATE ( [Repeat Buyers], dim_customers[days_to_repeat] <= 7,
                        KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) ),
            _eligible
        )
    )"""),
    ("Repeat Within 14 Days", "Customers", PCT1, """VAR _cut = DATE ( 2021, 1, 31 ) - 14
VAR _eligible = CALCULATE ( [Customers], KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) )
RETURN
    IF (
        _eligible >= 100,
        DIVIDE (
            CALCULATE ( [Repeat Buyers], dim_customers[days_to_repeat] <= 14,
                        KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) ),
            _eligible
        )
    )"""),
    ("Repeat Within 30 Days", "Customers", PCT1, """VAR _cut = DATE ( 2021, 1, 31 ) - 30
VAR _eligible = CALCULATE ( [Customers], KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) )
RETURN
    IF (
        _eligible >= 100,
        DIVIDE (
            CALCULATE ( [Repeat Buyers], dim_customers[days_to_repeat] <= 30,
                        KEEPFILTERS ( dim_customers[first_order_date] <= _cut ) ),
            _eligible
        )
    )"""),
    ("Eligible Customers 30 Days", "Customers", WHOLE,
     "CALCULATE ( [Customers], KEEPFILTERS ( dim_customers[first_order_date] <= DATE ( 2021, 1, 1 ) ) )"),
    ("Segment Action", "Customers", None, """SWITCH (
    SELECTEDVALUE ( dim_customers[rfm_segment] ),
    "Big one-off spenders", "Thank-you and a second-purchase offer within two weeks",
    "At risk", "One win-back email with a real reason to return",
    "Repeat, lapsing", "Personal note featuring their past categories",
    "Low-value one-offs", "No paid retargeting",
    "New customers", "Onboarding emails: the best chance of a second order",
    "Champions", "Early access and loyalty perks"
)"""),
    # Overview, acquisition, conversion and orders pages
    ("Revenue per Clean Day", "Sales", CUR0,
     "DIVIDE ( CALCULATE ( [Revenue], dim_date[is_revenue_tracking_ok] = TRUE () ), "
     "CALCULATE ( COUNTROWS ( dim_date ), dim_date[is_revenue_tracking_ok] = TRUE () ) )"),
    ("Single-Visit Order Share", "Attribution", PCT1, """DIVIDE (
    CALCULATE ( SUM ( fct_attribution_credits[credit] ), fct_attribution_credits[model] = "last_click",
                fct_attribution_credits[touches_in_path] = 1 ),
    CALCULATE ( SUM ( fct_attribution_credits[credit] ), fct_attribution_credits[model] = "last_click" )
)"""),
    ("Organic Search Markov CI", "Attribution", None,
     '"95% interval " & CALCULATE ( [Markov 95% CI], dim_channel[channel] = "Organic Search" )'),
    ("Step Base Sessions", "Funnel", WHOLE, """VAR _stage = SELECTEDVALUE ( dim_funnel_stage[stage_order] )
RETURN
    IF (
        _stage > 1,
        CALCULATE ( [Funnel Sessions], REMOVEFILTERS ( dim_funnel_stage ), dim_funnel_stage[stage_order] = _stage - 1 )
    )"""),
    ("Desktop Step Rate", "Funnel", PCT1, 'CALCULATE ( [Funnel Step Rate], dim_device[device_category] = "desktop" )'),
    ("Mobile Step Rate", "Funnel", PCT1, 'CALCULATE ( [Funnel Step Rate], dim_device[device_category] = "mobile" )'),
    ("Mobile Minus Desktop", "Funnel", None, """VAR _d = [Mobile Step Rate] - [Desktop Step Rate]
RETURN
    IF ( NOT ISBLANK ( [Mobile Step Rate] ), FORMAT ( _d * 100, "+0.0;-0.0;0.0" ) & " pts" )"""),
    # normal-approximation 95% interval for a difference of two proportions
    ("Mobile Minus Desktop CI", "Funnel", None, """VAR _pm = [Mobile Step Rate]
VAR _pd = [Desktop Step Rate]
VAR _nm = CALCULATE ( [Step Base Sessions], dim_device[device_category] = "mobile" )
VAR _nd = CALCULATE ( [Step Base Sessions], dim_device[device_category] = "desktop" )
VAR _d = _pm - _pd
VAR _se = SQRT ( DIVIDE ( _pm * ( 1 - _pm ), _nm ) + DIVIDE ( _pd * ( 1 - _pd ), _nd ) )
RETURN
    IF (
        NOT ISBLANK ( _pm ),
        FORMAT ( ( _d - 1.96 * _se ) * 100, "+0.0;-0.0;0.0" ) & " to "
            & FORMAT ( ( _d + 1.96 * _se ) * 100, "+0.0;-0.0;0.0" ) & " pts"
    )"""),
    ("Purchase Sessions", "Funnel", WHOLE, "CALCULATE ( [Sessions], fct_sessions[reached_purchase] = TRUE () )"),
    ("Session Purchase Rate", "Funnel", PCT2, "DIVIDE ( [Purchase Sessions], [Sessions] )"),
    ("Landing Session Share", "Traffic", PCT1,
     "DIVIDE ( [Sessions], CALCULATE ( [Sessions], REMOVEFILTERS ( fct_sessions[landing_page_group] ) ) )"),
    # Wilson score interval: stays sensible for small samples and rates near zero
    ("Session Purchase Rate CI", "Funnel", None, """VAR _n = [Sessions]
VAR _k = [Purchase Sessions]
VAR _z = 1.96
VAR _p = DIVIDE ( _k, _n )
VAR _centre = ( _p + _z * _z / ( 2 * _n ) ) / ( 1 + _z * _z / _n )
VAR _half = _z * SQRT ( _p * ( 1 - _p ) / _n + _z * _z / ( 4 * _n * _n ) ) / ( 1 + _z * _z / _n )
RETURN
    IF ( _n > 0, FORMAT ( _centre - _half, "0.00%" ) & " to " & FORMAT ( _centre + _half, "0.00%" ) )"""),
    ("Orders (Clean Value Days)", "Sales", WHOLE, "CALCULATE ( [Orders], dim_date[is_revenue_tracking_ok] = TRUE () )"),
    ("Median Order Value", "Sales", CUR0,
     "CALCULATE ( MEDIAN ( fct_orders[purchase_revenue_usd] ), dim_date[is_revenue_tracking_ok] = TRUE () )"),
    ("Mean Order Value", "Sales", CUR0, "CALCULATE ( [AOV], dim_date[is_revenue_tracking_ok] = TRUE () )"),
    ("Multi-Product Order Share", "Sales", PCT1, """DIVIDE (
    CALCULATE ( [Orders], fct_orders[basket_type] = "Several products" ),
    CALCULATE ( [Orders], fct_orders[basket_type] <> "No item detail" )
)"""),
    ("Top Decile Order Revenue Share", "Sales", PCT1, """VAR _orders = CALCULATETABLE ( fct_orders, dim_date[is_revenue_tracking_ok] = TRUE () )
VAR _top = TOPN ( INT ( COUNTROWS ( _orders ) * 0.1 ), _orders, fct_orders[purchase_revenue_usd], DESC )
RETURN
    DIVIDE ( SUMX ( _top, fct_orders[purchase_revenue_usd] ), SUMX ( _orders, fct_orders[purchase_revenue_usd] ) )"""),
    ("Product Orders", "Products", WHOLE, "DISTINCTCOUNT ( fct_order_items[order_id] )"),
    ("Product Revenue Share", "Products", PCT1, """DIVIDE (
    SUM ( fct_order_items[item_revenue_usd] ),
    CALCULATE ( SUM ( fct_order_items[item_revenue_usd] ),
                REMOVEFILTERS ( fct_order_items[item_name], fct_order_items[item_category] ) )
)"""),
    ("Pair Orders", "Products", WHOLE, "SUM ( mart_product_pairs[orders_together] )"),
    ("Pair Lift", "Products", "0.0", "SUM ( mart_product_pairs[lift] )"),
    ("Apparel Highlight Color", "Formatting", None, highlight("fct_order_items[item_category]", "Apparel")),
    # Formatting measures (colours as text; used by conditional formatting, never shown as numbers)
    ("Channel Highlight Color", "Formatting", None, highlight("dim_channel[channel]", "Organic Search")),
    ("Referral Highlight Color", "Formatting", None, highlight("dim_channel[channel]", "Referral")),
    ("January Highlight Color", "Formatting", None, highlight("dim_date[month_label]", "Jan 2021")),
    # Session Share is defined with the overview measures below
    ("Country Highlight Color", "Formatting", None, highlight("fct_sessions[geo_country]", "United States")),
    # Blank outside the eight countries with the most sessions, so the bar chart shows only those
    ("Top 8 Country Share", "Traffic", PCT1, """VAR _rank = RANKX ( ALLSELECTED ( fct_sessions[geo_country] ), [Sessions] )
RETURN
    IF ( _rank <= 8, [Session Share] )"""),
]

# Period comparison for every KPI: previous period (same number of days immediately before the selection),
# a readable change label ("▲ 12.4% vs previous period") and the label's colour.
_FORMATS = {name: fmt for name, _, fmt, _ in MEASURES}
for _base in KPI_BASES:
    MEASURES += [
        (f"{_base} PP", "Period comparison", _FORMATS[_base], prev_period(_base)),
        (f"{_base} Change", "Period comparison", None, change_label(_base, is_rate=_base in RATE_KPIS)),
        (f"{_base} Change Color", "Formatting", None, change_color(_base)),
    ]

# ---- measures for the dark "Night" overview report -------------------------------------------------------
_D = DARK_PALETTE
MEASURES += [
    ("Organic Search Sessions", "Traffic", WHOLE, 'CALCULATE ( [Sessions], dim_channel[channel] = "Organic Search" )'),
    ("Direct Sessions", "Traffic", WHOLE, 'CALCULATE ( [Sessions], dim_channel[channel] = "Direct" )'),
    ("Other Sessions", "Traffic", WHOLE, "[Sessions] - [Organic Search Sessions] - [Direct Sessions]"),
    ("Session Share", "Traffic", PCT1,
     "DIVIDE ( [Sessions], CALCULATE ( [Sessions], REMOVEFILTERS ( fct_sessions[geo_country] ) ) )"),
    ("Sessions vs PP", "Period comparison", "+0%;-0%;0%", "DIVIDE ( [Sessions] - [Sessions PP], [Sessions PP] )"),
    ("Revenue per Day", "Sales", CUR0, "DIVIDE ( [Revenue], COUNTROWS ( dim_date ) )"),
    ("Product Revenue", "Products", CUR0, "SUM ( fct_order_items[item_revenue_usd] )"),
    ("Units Sold", "Products", WHOLE, "SUM ( fct_order_items[quantity] )"),
    *[(f"{r} Remainder", "Funnel", PCT1, f"IF ( NOT ISBLANK ( [{r}] ), 1 - [{r}] )")
      for r in ("Session to View Rate", "View to Cart Rate", "Cart to Checkout Rate", "Checkout to Purchase Rate")],
    *[(f"{b} Change Color Dark", "Formatting", None, change_color(b, _D["POSITIVE"], _D["NEGATIVE"], _D["MUTED"]))
      for b in ("Revenue", "Orders", "Sessions", "Conversion Rate")],
    ("Sunday Highlight Color Dark", "Formatting", None,
     highlight("dim_date[day_name]", "Sun", _D["ACCENT"], _D["PRIMARY"])),
]


def parquet_columns(table: str) -> list[tuple[str, str]]:
    path = (SERVING / f"{table}.parquet").as_posix()
    return [(r[0], r[1]) for r in duckdb.sql(f"DESCRIBE SELECT * FROM '{path}'").fetchall()]


def m_source(lines: list[str]) -> list[str]:
    return ["\t\tsource ="] + [f"\t\t\t\t{line}" for line in lines]


def table_tmdl(name: str, spec: TableSpec) -> str:
    out = [f"table {q(name)}", f"\tlineageTag: {tag('table', name)}"]
    if spec.is_date_table:
        out.append("\tdataCategory: Time")
    out.append("")
    for col, duck_type in parquet_columns(name):
        dtype = DUCK_TO_TMDL[duck_type.split("(")[0]]
        out += [f"\tcolumn {q(col)}", f"\t\tdataType: {dtype}"]
        fmt = (spec.formats or {}).get(col) or {"int64": "0", "double": "#,0.00", "dateTime": "General Date"}.get(dtype)
        if dtype == "dateTime" and duck_type == "DATE" and not (spec.formats or {}).get(col):
            fmt = "dd mmm yyyy"
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        if spec.is_date_table and col == "date":
            out.append("\t\tisKey")
        if col in spec.hidden:
            out.append("\t\tisHidden")
        if spec.data_categories and col in spec.data_categories:
            out.append(f"\t\tdataCategory: {spec.data_categories[col]}")
        out += [f"\t\tlineageTag: {tag('column', name, col)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {col}"]
        if spec.sort_by and col in spec.sort_by:
            out.append(f"\t\tsortByColumn: {q(spec.sort_by[col])}")
        out += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
    out += [f"\tpartition {q(name)} = m", "\t\tmode: import"]
    out += m_source(["let",
                     f'    Source = Parquet.Document(File.Contents(DataFolder & "{name}.parquet"))',
                     "in",
                     "    Source"])
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def measures_table_tmdl() -> str:
    out = ["table _Measures", f"\tlineageTag: {tag('table', '_Measures')}", ""]
    for name, folder, fmt, dax in MEASURES:
        lines = dax.strip().splitlines()
        if len(lines) == 1:
            out.append(f"\tmeasure {q(name)} = {lines[0]}")
        else:
            out.append(f"\tmeasure {q(name)} =")
            out += [f"\t\t\t{line}" for line in lines]
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {tag('measure', name)}", ""]
    out += ["\tcolumn Placeholder", "\t\tdataType: string", "\t\tisHidden",
            f"\t\tlineageTag: {tag('column', '_Measures', 'Placeholder')}", "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Placeholder", "", "\t\tannotation SummarizationSetBy = Automatic", "",
            "\tpartition _Measures = m", "\t\tmode: import"]
    out += m_source(["let", "    Source = #table(type table [Placeholder = text], {})", "in", "    Source"])
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, obj) -> None:
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def build_semantic_model() -> None:
    d = SM_DIR / "definition"
    write_json(SM_DIR / "definition.pbism", {
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    write(d / "database.tmdl", f"database {NAME}\n\tcompatibilityLevel: 1600\n")
    all_tables = ["_Measures", *TABLES]
    write(d / "model.tmdl", "\n".join([
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: en-GB",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        "annotation PBI_QueryOrder = " + json.dumps(["DataFolder", *all_tables]),
        "",
        *[f"ref table {q(t)}" for t in all_tables],
        "",
    ]))
    folder = str(SERVING) + "\\"
    write(d / "expressions.tmdl", "\n".join([
        f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
        f"\tlineageTag: {tag('expression', 'DataFolder')}",
        "",
        "\tannotation PBI_ResultType = Text",
        "",
    ]))
    rel = []
    for many_t, many_c, one_t, one_c in RELATIONSHIPS:
        rel += [f"relationship {tag('rel', many_t, many_c, one_t)}",
                f"\tfromColumn: {q(many_t)}.{q(many_c)}",
                f"\ttoColumn: {q(one_t)}.{q(one_c)}"]
        if one_t == "dim_date":
            rel.append("\tjoinOnDateBehavior: datePartOnly")
        rel.append("")
    write(d / "relationships.tmdl", "\n".join(rel))
    write(d / "tables" / "_Measures.tmdl", measures_table_tmdl())
    for t, spec in TABLES.items():
        write(d / "tables" / f"{t}.tmdl", table_tmdl(t, spec))


def write_measures_reference() -> None:
    """Human-readable copy of every measure, kept in sync with the model."""
    out = ["// Generated by dashboard/build_pbip.py; edit the MEASURES list there, not this file.", ""]
    folder = None
    for name, fld, fmt, dax in MEASURES:
        if fld != folder:
            out += ["", f"// ---------------------------------------------------------------- {fld.upper()}", ""]
            folder = fld
        out.append(f"[{name}] =\n{dax.strip()}")
        out.append(f"// Format: {fmt or 'text'}\n")
    write(PBI_DIR / "measures.dax", "\n".join(out))


# ---- KPI dictionary (dashboard/KPI_DICTIONARY.md) --------------------------------------------------------
# Plain-English definitions for every measure a page shows. The DAX and format come from MEASURES above,
# so the document can't drift from the model. (page, [(measure, definition, caveat)])
KPI_DOCS = [
    ("Overview", [
        ("Revenue", "Sum of deduplicated order revenue (USD).", "26 to 31 Jan under-recorded: order values missing."),
        ("Orders", "Count of deduplicated orders (by transaction ID, or session + amount + basket when the ID is missing).",
         "Range 4,451 to 5,357 depending on how the 906 ID-less purchases are treated; 5,288 with the project's rule."),
        ("Sessions", "Count of GA4 sessions (user + session ID).", ""),
        ("Conversion Rate", "Orders ÷ sessions, all days.", "Not the same as the funnel's 'sessions with a purchase' (1.35%)."),
        ("Revenue Change", "Change vs the previous period of the same length, as text with ▲ or ▼; one per KPI.",
         "Blank ('No prior period') when the selection starts on 1 Nov."),
        ("Attributed Revenue", "Revenue credited to each channel by the selected attribution model (default: last click, self-referrals removed).", ""),
        ("Revenue per Clean Day", "Revenue ÷ days, counting only days with recorded order values.", "Excludes 26 to 31 Jan."),
    ]),
    ("Acquisition & attribution", [
        ("Engagement Rate", "Engaged sessions ÷ sessions (GA4's engaged-session flag).", ""),
        ("Self-Referral Orders", "Orders whose converting session came from the store's own domain (customers back from the payment page).",
         "A tracking artefact, not a channel; corrected attribution reassigns them."),
        ("Attributed Share", "Share of order credit per channel under each model; drives the seven-model heatmap.", ""),
        ("Orders (Naive Last Click)", "Last-click orders as GA4 reports them (self-referrals included).", ""),
        ("Orders (Corrected Last Click)", "Last-click orders with self-referrals removed; journeys with no earlier visit are 'Unknown'.", ""),
        ("Markov Share", "Data-driven (Markov chain) share of conversions per channel.", "Covers the whole period: date filters don't apply."),
        ("Markov 95% CI", "95% bootstrap interval for the Markov share (200 resamples, fixed seed).", ""),
        ("Organic Search Markov Share", "Organic Search's Markov share, for the KPI card.", ""),
        ("Single-Visit Order Share", "Share of orders whose journey has one visit, where every model gives the same answer.", ""),
        ("Session Share", "A country's share of sessions.", ""),
        ("Top 8 Country Share", "Session Share for the eight countries with the most sessions; blank for the rest.", "Ranked within the current filters."),
    ]),
    ("Conversion & landing pages", [
        ("Session to View Rate", "Sessions that viewed a product ÷ sessions.", "Days with working cart tracking only (70 days)."),
        ("View to Cart Rate", "Sessions that added to cart ÷ sessions that viewed a product. The biggest leak.", "70 clean days."),
        ("Cart to Checkout Rate", "Sessions that began checkout ÷ sessions that added to cart.", "70 clean days."),
        ("Checkout to Purchase Rate", "Sessions that purchased ÷ sessions that began checkout.", "70 clean days."),
        ("Funnel Sessions", "Sessions reaching the funnel step on the row (clean days).", ""),
        ("Funnel Step Rate", "Share of the previous step that continued to this one.", ""),
        ("Desktop Step Rate", "Funnel Step Rate for desktop sessions only (Mobile Step Rate likewise).", "Overrides the Device slicer on purpose."),
        ("Mobile Minus Desktop", "Difference between the mobile and desktop step rates, in percentage points.", ""),
        ("Mobile Minus Desktop CI", "95% interval for that difference (normal approximation).", "Every step's interval includes zero."),
        ("Session Purchase Rate", "Sessions with a purchase ÷ sessions, per landing page.", ""),
        ("Session Purchase Rate CI", "95% Wilson interval for that rate.", "Pages with fewer than 1,000 sessions are grouped as 'Other pages'."),
        ("Landing Session Share", "A landing page's share of all sessions.", ""),
    ]),
    ("Customers & retention", [
        ("Customers", "Browsers (user_pseudo_id) with at least one order.", "A person on two devices counts twice."),
        ("Repeat Customer Rate", "Customers who bought on 2+ different days ÷ customers.", ""),
        ("Median Customer Spend", "Median total spend per customer.", ""),
        ("Big Spender Revenue Share", "Share of customer revenue from the 'Big one-off spenders' segment.", ""),
        ("Back Within 14 Days", "Repeat buyers whose second buying day came within 14 days of the first ÷ repeat buyers.", ""),
        ("Share of Customers", "A segment's share of customers (Share of Revenue likewise for revenue).", ""),
        ("Repeat Within 30 Days", "Customers who bought again within 30 days ÷ customers who could be followed 30 days (7 and 14 likewise).",
         "Blank when fewer than 100 customers could be followed that long."),
        ("Eligible Customers 30 Days", "Customers whose first purchase was at least 30 days before 31 Jan.", ""),
        ("Segment Action", "The suggested action for each segment, as text.", ""),
    ]),
    ("Orders & products", [
        ("Orders (Clean Value Days)", "Orders on days with recorded order values.", "Excludes 26 to 31 Jan."),
        ("Median Order Value", "Median order value on days with recorded values.", ""),
        ("Mean Order Value", "Average order value on days with recorded values.", "Pulled up by large orders; read with the median."),
        ("Multi-Product Order Share", "Orders with 2+ different products ÷ orders with item detail.", ""),
        ("Top Decile Order Revenue Share", "Revenue from the top 10% of orders by value ÷ all revenue (clean days).", ""),
        ("Product Revenue", "Sum of item revenue (Units Sold, Product Orders likewise).", ""),
        ("Product Revenue Share", "A product's or category's share of all product revenue.", ""),
        ("Pair Orders", "Orders containing both products of a pair (pairs in 30+ orders only).", "Full period, from mart_product_pairs."),
        ("Pair Lift", "How many times more often the pair is bought together than chance.", ""),
    ]),
]
FORMAT_NAMES = {WHOLE: "Whole number", PCT1: "Percent, 1 dp", PCT2: "Percent, 2 dp", CUR0: "USD, whole", CUR2: "USD, 2 dp",
                None: "Text", "+0%;-0%;0%": "Signed percent", "+#,0;-#,0;0": "Signed whole number", "0.0": "Number, 1 dp"}


def write_kpi_dictionary() -> None:
    """dashboard/KPI_DICTIONARY.md: every KPI with its definition, caveat, format and the exact DAX."""
    by_name = {name: (fmt, dax) for name, _, fmt, dax in MEASURES}
    out = ["# KPI dictionary", "",
           "Every measure the dashboard pages show: what it means, its caveats, its format and its exact DAX. "
           "Generated by `dashboard/build_pbip.py` from the model itself, so it always matches the dashboard. "
           "All other measures (helpers, colours, previous-period values) are in [`measures.dax`](measures.dax).", ""]
    for page, items in KPI_DOCS:
        out += [f"## {page}", "", "| KPI | What it means | Caveat | Format |", "|---|---|---|---|"]
        for name, definition, caveat in items:
            fmt, _ = by_name[name]
            out.append(f"| **{name}** | {definition} | {caveat} | {FORMAT_NAMES.get(fmt, fmt)} |")
        out += ["", "<details><summary>DAX for this page</summary>", ""]
        for name, *_ in items:
            out += [f"**{name}**", "", "```dax", by_name[name][1].strip(), "```", ""]
        out += ["</details>", ""]
    write(PBI_DIR / "KPI_DICTIONARY.md", "\n".join(out))


# =====================================================================================
# REPORT
# =====================================================================================

def lit(v) -> dict:
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def raw(value: str) -> dict:
    """A literal passed through unquoted (e.g. pre-quoted font family strings)."""
    return {"expr": {"Literal": {"Value": value}}}


def solid(hex_color: str) -> dict:
    return {"solid": {"color": lit(hex_color)}}


def measure_color(measure: str) -> dict:
    """Conditional colour driven by a measure that returns a hex code (field-value formatting)."""
    return {"solid": {"color": {"expr": mea(measure)}}}


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": prop}}


def ref(field: dict) -> tuple[str, str]:
    kind = next(iter(field))
    return field[kind]["Expression"]["SourceRef"]["Entity"], field[kind]["Property"]


def named(field: dict, label: str) -> dict:
    """Field with a friendly column header (e.g. geo_country -> Country)."""
    return {**field, "_display": label}


def exclude(entity: str, prop: str, values: list[str]) -> dict:
    """Visual-level filter: entity[prop] NOT IN values."""
    return {"name": tag("filter", entity, prop, *values).replace("-", "")[:20], "field": col(entity, prop),
            "type": "Categorical", "filter": {
                "Version": 2, "From": [{"Name": "f", "Entity": entity, "Type": 0}],
                "Where": [{"Condition": {"Not": {"Expression": {"In": {
                    "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}],
                    "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values]}}}}}]}}


def proj(field: dict, active: bool = False) -> dict:
    field = dict(field)
    display = field.pop("_display", None)
    entity, prop = ref(field)
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    if active:
        p["active"] = True
    return p


def props(**kw) -> list[dict]:
    return [{"properties": {k: (v if isinstance(v, dict) else lit(v)) for k, v in kw.items()}}]


def all_points(properties: dict) -> dict:
    """Formatting rule applied to every data point (needed for measure-driven colours)."""
    return {"properties": properties, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}


def gradient(measure: str, lo: str = HEAT_MIN, hi: str = HEAT_MAX) -> dict:
    return {
        "properties": {"backColor": {"solid": {"color": {"expr": {"FillRule": {
            "Input": mea(measure),
            "FillRule": {"linearGradient2": {
                "min": {"color": {"Literal": {"Value": f"'{lo}'"}}},
                "max": {"color": {"Literal": {"Value": f"'{hi}'"}}},
                "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'noColor'"}}},
            }},
        }}}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": f"_Measures.{measure}"},
    }


# ---- formatting presets (design system §2.8) ----------------------------------------------------------

def axes(value_axis: bool = True, inner_padding: int | None = None, min_category: int | None = None,
         max_margin: int | None = None) -> dict:
    """Quiet axes: no titles, 8pt muted labels, dotted value gridlines only."""
    cat = {"showAxisTitle": False, "labelColor": solid(MUTED), "fontSize": 8, "gridlineShow": False}
    if inner_padding is not None:
        cat["innerPadding"] = inner_padding
    if min_category is not None:
        cat["minCategoryWidth"] = min_category
    if max_margin is not None:  # % of the visual the category labels may take
        cat["maxMarginFactor"] = max_margin
    val = {"show": value_axis, "showAxisTitle": False, "labelColor": solid(MUTED), "fontSize": 8,
           "gridlineShow": True, "gridlineColor": solid(BORDER), "gridlineThickness": 1, "gridlineStyle": "dotted"}
    return {"categoryAxis": props(**cat), "valueAxis": props(**val)}


def labels(units: int = 0, precision: int | None = None, show: bool = True) -> dict:
    """Data labels. units: 0 auto, 1 none, 1000 thousands."""
    p = {"show": show, "fontSize": 8, "color": solid(INK_2), "labelDisplayUnits": units}
    if precision is not None:
        p["labelPrecision"] = precision
    return {"labels": props(**p)}


def bar_chart(color_measure: str | None = None, units: int = 0, precision: int | None = None) -> dict:
    """Ranked horizontal bar: labels on bar ends replace the value axis (Datawrapper-style)."""
    objects = {**axes(value_axis=False, inner_padding=35, min_category=14), **labels(units, precision),
               "legend": props(show=False)}
    if color_measure:
        objects["dataPoint"] = [all_points({"fill": measure_color(color_measure)})]
    return objects


def column_chart(color_measure: str | None = None, units: int = 0, precision: int | None = None) -> dict:
    objects = {**axes(inner_padding=40), **labels(units, precision), "legend": props(show=False)}
    if color_measure:
        objects["dataPoint"] = [all_points({"fill": measure_color(color_measure)})]
    return objects


def table_style(widths: dict[str, int] | None = None) -> dict:
    """Quiet table. widths (queryRef -> px) fixes column widths so long text wraps instead of scrolling sideways."""
    style = {
        "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=solid(BORDER), rowPadding=4),
        "columnHeaders": props(fontColor=solid(INK_2), fontSize=9, fontFamily=raw(SEMIBOLD),
                               backColor=solid(CARD), wordWrap=True, autoSizeColumnWidth=not widths),
        "values": [{"properties": {"fontColor": solid(INK), "fontSize": lit(9), "wordWrap": lit(True),
                                   "backColorPrimary": solid(CARD), "backColorSecondary": solid(CARD)}}],
        "total": props(fontFamily=raw(SEMIBOLD), backColor=solid(CARD), fontColor=solid(INK)),
    }
    if widths:
        style["columnWidth"] = [{"properties": {"value": lit(w)}, "selector": {"metadata": q_ref}}
                                for q_ref, w in widths.items()]
    return style


def text_run(value: str, size: int, color: str, bold: bool = False) -> dict:
    style = {"fontSize": f"{size}pt", "color": color,
             "fontFamily": "'Segoe UI Semibold', wf_segoe-ui_semibold, helvetica, arial, sans-serif" if bold
             else "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"}
    return {"value": value, "textStyle": style}


def transparent() -> dict:
    """No background, border or title, and no padding (the theme's 16px would clip small text boxes)."""
    return {"background": props(show=False), "border": props(show=False), "title": props(show=False),
            "dropShadow": props(show=False), "padding": props(top=0, bottom=0, left=0, right=0)}


class Page:
    def __init__(self, name: str, display: str, width: int = 1280, height: int = 720):
        self.name, self.display, self.width, self.height = name, display, width, height
        self.visuals: list[dict] = []
        self.interactions: list[dict] = []

    def add(self, name: str, vtype: str, x, y, w, h, roles: dict | None = None, sort: list | None = None,
            title: str | None = None, subtitle: str | None = None, alt: str | None = None,
            objects: dict | None = None, container: dict | None = None, filters: list | None = None) -> str:
        visual: dict = {"visualType": vtype}
        if roles:
            query: dict = {"queryState": {
                role: {"projections": [proj(f, active=(role in ("Category", "Rows") and i == 0))
                                       for i, f in enumerate(fields)]}
                for role, fields in roles.items()}}
            if sort:
                query["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort],
                                           "isDefaultSort": True}
            visual["query"] = query
        if objects:
            visual["objects"] = objects
        vco = dict(container or {})
        if title:
            vco["title"] = props(show=True, text=title)
        if subtitle:
            vco["subTitle"] = props(show=True, text=subtitle)
        if alt:
            vco["general"] = props(altText=alt)
        if vco:
            visual["visualContainerObjects"] = vco
        visual["drillFilterOtherVisuals"] = True
        container_doc = {
            "$schema": VISUAL_SCHEMA,
            "name": name,
            "position": {"x": x, "y": y, "z": len(self.visuals) * 100, "height": h, "width": w,
                         "tabOrder": len(self.visuals) * 100},
            "visual": visual,
        }
        if filters:
            container_doc["filterConfig"] = {"filters": filters}
        self.visuals.append(container_doc)
        return name

    # ---- page furniture (docs/design_system.md) ---------------------------------------------------------

    def header(self, title: str, headline: str, meta: str = ""):
        """Page title and one-line finding on the left; data period and treatment on the right."""
        y, h = BAND["header"]
        self.add(f"{self.name}_header", "textbox", gx(0), y, gw(9), h, objects={"general": [{"properties": {
            "paragraphs": [{"textRuns": [text_run(title, 20, INK, bold=True)]},
                           {"textRuns": [text_run(headline, 11, INK_2)]}]}}]},
                 container={**transparent(), "padding": props(top=0, bottom=0, left=0, right=0)})
        meta = meta or "1 Nov 2020 to 31 Jan 2021 · historical GA4 sample · corrected for four tracking faults"
        self.add(f"{self.name}_meta", "textbox", gx(9), y, gw(3), h, objects={"general": [{"properties": {
            "paragraphs": [{"textRuns": [text_run(meta, 8, MUTED)], "horizontalTextAlignment": "right"}]}}]},
                 container={**transparent(), "padding": props(top=8, bottom=0, left=0, right=0)})

    def sidebar(self, slicers: list[tuple[str, dict, str]]):
        """Dark slate sidebar: product name, slicers, page buttons and the independence note (items sit on the panel: _ovl)."""
        self.add(f"{self.name}_side", "textbox", 0, 0, SIDE_W, self.height, objects={"general": [{"properties": {
            "paragraphs": [{"textRuns": [text_run("Merch Store", 16, SIDE_TEXT, bold=True)]},
                           {"textRuns": [text_run("Analytics Review", 16, SIDE_MUTED, bold=True)]}]}}]},
            container={"background": props(show=True, color=solid(SIDE_BG)),
                       "border": props(show=False, radius=0),
                       "padding": props(top=24, bottom=0, left=20, right=20)})
        for i, (key, field, label) in enumerate(slicers):
            self.add(f"{self.name}_slicer_{key}_ovl", "slicer", 16, 104 + i * 72, SIDE_W - 32, 60,
                     roles={"Values": [field]},
                     objects={"data": props(mode="Dropdown"), "header": props(show=False),
                              "items": props(fontColor=solid(INK), fontSize=10)},
                     container={"background": props(show=True, color=solid(CARD)),
                                "border": props(show=False, radius=8),
                                "title": props(show=True, text=label, fontSize=9, fontColor=solid(INK_2),
                                               fontFamily=raw(REGULAR)),
                                "padding": props(top=4, bottom=4, left=10, right=10)})
        top = 104 + len(slicers) * 72 + 16
        self.add(f"{self.name}_nav_label_ovl", "textbox", 16, top, SIDE_W - 32, 24, objects={"general": [{"properties": {
            "paragraphs": [{"textRuns": [text_run("Pages", 9, SIDE_MUTED, bold=True)]}]}}]}, container=transparent())
        for i, (page_name, label) in enumerate(LIGHT_NAV):
            here = page_name == self.name
            self.add(f"{self.name}_nav_{page_name}_ovl", "actionButton", 16, top + 28 + i * 44, SIDE_W - 32, 36,
                     objects=nav_button(label, here),
                     container={"background": props(show=False), "border": props(show=False),
                                "padding": props(top=0, bottom=0, left=0, right=0),
                                "visualLink": props(show=True, type="PageNavigation", navigationSection=page_name,
                                                    tooltip=f"Go to {label}")},
                     alt=f"Go to the {label} page")
        self.add(f"{self.name}_note_ovl", "textbox", 16, self.height - 140, SIDE_W - 32, 124,
                 objects={"general": [{"properties": {"paragraphs": [
                     {"textRuns": [text_run("▲▼ compare with the previous period of the same length. "
                                            "Red marks the one thing to look at.", 8, SIDE_MUTED)]},
                     {"textRuns": [text_run(" ", 4, SIDE_MUTED)]},
                     {"textRuns": [text_run(INDEPENDENCE, 8, SIDE_MUTED)]}]}}]},
                 container=transparent())

    def kpi_band(self, items: list[dict]):
        """One card per KPI with a thin colour bar on top: label, value, then the change vs previous period
        (or a context line)."""
        y, h = BAND["kpi"]
        gap = GUTTER
        card_w = (gw(12) - gap * (len(items) - 1)) // len(items)
        for i, it in enumerate(items):
            cx = gx(0) + i * (card_w + gap)
            key = f"{self.name}_kpi{i}"
            self.add(f"{key}_card", "textbox", cx, y, card_w, h,
                     objects={"general": [{"properties": {"paragraphs": [{"textRuns": [text_run(" ", 6, INK)]}]}}]},
                     container={"title": props(show=False)})
            self.add(f"{key}_bar_ovl", "textbox", cx, y, card_w, 4,
                     objects={"general": [{"properties": {"paragraphs": [{"textRuns": [text_run(" ", 1, INK)]}]}}]},
                     container={"background": props(show=True, color=solid(KPI_ACCENTS[i % len(KPI_ACCENTS)])),
                                "border": props(show=False, radius=0), "title": props(show=False),
                                "padding": props(top=0, bottom=0, left=0, right=0)})
            x, cell = cx - 8, card_w + 16  # value and change text sit inside the card, 8px in from its edges
            units, precision = it.get("units", 1), it.get("precision")
            label_props = dict(fontSize=26, color=solid(it.get("color", INK)), fontFamily=raw(REGULAR),
                               labelDisplayUnits=units)
            if precision is not None:
                label_props["labelPrecision"] = precision
            self.add(f"{key}_value_ovl", "card", x + 8, y + 6, cell - 16, 64, roles={"Values": [mea(it["measure"])]},
                     objects={"labels": props(**label_props), "categoryLabels": props(show=False)},
                     container={"background": props(show=False), "border": props(show=False),
                                "title": props(show=True, text=it["label"], fontSize=9, fontColor=solid(INK_2),
                                               fontFamily=raw(REGULAR), alignment="left"),
                                "padding": props(top=8, bottom=0, left=16, right=8)},
                     alt=f"{it['label']} KPI")
            if it.get("context"):
                self.add(f"{key}_context_ovl", "textbox", x + 8, y + 70, cell - 16, 28,
                         objects={"general": [{"properties": {"paragraphs": [
                             {"textRuns": [text_run(it["context"], 8, MUTED)]}]}}]},
                         container={**transparent(), "padding": props(top=0, bottom=0, left=16, right=8)})
            elif it.get("context_measure"):
                self.add(f"{key}_context_ovl", "card", x + 8, y + 70, cell - 16, 28,
                         roles={"Values": [mea(it["context_measure"])]},
                         objects={"labels": props(fontSize=8, color=solid(MUTED), fontFamily=raw(REGULAR)),
                                  "categoryLabels": props(show=False)},
                         container={"background": props(show=False), "border": props(show=False),
                                    "title": props(show=False), "padding": props(top=0, bottom=0, left=16, right=8)})
            else:
                base = it["measure"]
                self.add(f"{key}_change_ovl", "card", x + 8, y + 70, cell - 16, 28, roles={"Values": [mea(f"{base} Change")]},
                         objects={"labels": props(fontSize=8, color=measure_color(f"{base} Change Color"),
                                                  fontFamily=raw(SEMIBOLD)),
                                  "categoryLabels": props(show=False)},
                         container={"background": props(show=False), "border": props(show=False),
                                    "title": props(show=False), "padding": props(top=0, bottom=0, left=16, right=8)})

    def decision_strip(self, items: list[tuple[str, str]]):
        """Four short panels that close the page: finding, evidence, interpretation, next action (or topic headings)."""
        y, h = BAND["decision"]
        for i, (heading, text) in enumerate(items):
            self.add(f"{self.name}_decision{i}", "textbox", gx(i * 3), y, gw(3), h,
                     objects={"general": [{"properties": {"paragraphs": [
                         {"textRuns": [text_run(heading.upper(), 7, PRIMARY_STRONG, bold=True)]},
                         {"textRuns": [text_run(text, 8, INK)]}]}}]},
                     container={"background": props(show=True, color=solid(SELECTED)),
                                "border": props(show=False, radius=8),
                                "padding": props(top=6, bottom=4, left=12, right=12)})

    def note(self, name: str, col_: int, span: int, band: str, title: str, lines: list[str]):
        """Plain text panel (e.g. possible explanations), styled like a chart card."""
        y, h = BAND[band]
        paragraphs = [{"textRuns": [text_run(title, 11, INK, bold=True)]}, {"textRuns": [text_run(" ", 4, INK)]}]
        paragraphs += [{"textRuns": [text_run(line, 9, INK_2 if not line.startswith("→") else INK)]} for line in lines]
        self.add(name, "textbox", gx(col_), y, gw(span), h, objects={"general": [{"properties": {"paragraphs": paragraphs}}]},
                 container={"padding": props(top=16, bottom=16, left=16, right=16)})

    def footer(self, note: str = ""):
        y, h = BAND["footer"]
        text = ("Source: GA4 public sample, Google Merchandise Store · orders deduplicated · self-referrals removed · "
                "funnel skips 22 days with a broken cart tag · order values missing 26 to 31 Jan" + note)
        self.add(f"{self.name}_footer", "textbox", gx(0), y, gw(12), h,
                 objects={"general": [{"properties": {"paragraphs": [{"textRuns": [text_run(text, 8, MUTED)]}]}}]},
                 container=transparent())


# ---- light pages ----------------------------------------------------------------------------------
# Titles state a finding only where the full-period data supports it (docs/design_system.md).

LIGHT_NAV = [("exec", "Overview"), ("acquisition", "Acquisition & attribution"),
             ("conversion", "Conversion & landing pages"), ("customers", "Customers & retention"),
             ("orders", "Orders & products")]
MONTH = ("month", col("dim_date", "month_label"), "Period")
DEVICE = ("device", col("dim_device", "device_category"), "Device")
CHANNEL = ("channel", col("dim_channel", "channel"), "Channel")


def nav_button(label: str, here: bool) -> dict:
    """Sidebar page button: the current page has a lighter slate fill and frost-blue text."""
    default = {"selector": {"id": "default"}}
    return {
        "text": [{"properties": {"show": lit(True)}},
                 {"properties": {"text": lit(label), "fontSize": lit(10), "horizontalAlignment": lit("left"),
                                 "leftMargin": lit(12),
                                 "fontColor": solid(SIDE_SELECTED_TEXT if here else SIDE_MUTED),
                                 "fontFamily": raw(SEMIBOLD if here else REGULAR)}, **default}],
        "icon": [{"properties": {"show": lit(False)}}],
        "fill": [{"properties": {"show": lit(here)}},
                 {"properties": {"fillColor": solid(SIDE_SELECTED), "transparency": lit(0)}, **default}],
        "outline": [{"properties": {"show": lit(False)}}],
        "shape": [{"properties": {"tileShape": lit("rectangleRounded"), "roundEdge": lit(18)}}],
    }


def light_page(name: str, display: str, title: str, headline: str, slicers: list, meta: str = "") -> Page:
    p = Page(name, display, width=1440, height=900)
    p.sidebar(slicers)
    p.header(title, headline, meta)
    return p


def kpis(*items: tuple) -> list[dict]:
    """(label, measure) or (label, measure, units, precision): KPIs with a change vs previous period."""
    out = []
    for it in items:
        d = {"label": it[0], "measure": it[1]}
        if len(it) > 2:
            d["units"], d["precision"] = it[2], it[3]
        out.append(d)
    return out


def page_executive() -> Page:
    p = light_page("exec", "Overview", "Store performance review",
                   "January revenue fell because conversion weakened, not simply because traffic declined.",
                   [MONTH, DEVICE, CHANNEL])
    p.kpi_band(kpis(("Revenue", "Revenue", 1000, 1), ("Orders", "Orders"), ("Sessions", "Sessions", 1000, 1),
                    ("Conversion rate", "Conversion Rate")))

    y, h = BAND["primary"]
    p.add("exec_trend", "lineChart", gx(0), y, gw(8), h,
          roles={"Category": [col("dim_date", "date")], "Y": [mea("Revenue")]},
          sort=[(col("dim_date", "date"), "Ascending")],
          objects={**axes(), "legend": props(show=False),
                   "lineStyles": props(strokeWidth=2, showMarker=False, areaShow=True),
                   "dataPoint": [{"properties": {"fill": solid(PRIMARY)}, "selector": {"metadata": "_Measures.Revenue"}},
                                 {"properties": {"transparency": lit(85)}}]},
          title="Revenue peaked from Cyber Monday to mid-December, then fell in January",
          subtitle="Daily revenue (USD), deduplicated orders · the last six days read low because order values "
                   "weren't recorded (26 to 31 Jan)",
          alt="Area chart of daily revenue from November 2020 to January 2021; highest from 30 November to mid-December.")
    p.add("exec_driver", "barChart", gx(8), y, gw(4), h,
          roles={"Category": [col("dim_channel", "channel")], "Y": [mea("Attributed Revenue")]},
          sort=[(mea("Attributed Revenue"), "Descending")],
          objects=bar_chart("Channel Highlight Color", units=1000, precision=0),
          title="Organic Search is credited with the most revenue",
          subtitle="Revenue by channel · corrected last click (self-referrals removed)",
          alt="Bar chart ranking channels by credited revenue; Organic Search highlighted as the largest.")

    y, h = BAND["support"]
    for i, (name, measure, title, sub, units) in enumerate([
            ("sessions", "Sessions", "Traffic dipped 11% in January…", "Sessions by month", 1000),
            ("cvr", "Conversion Rate", "…but conversion fell by almost half…", "Orders ÷ sessions, by month", 0),
            ("rpd", "Revenue per Clean Day", "…so revenue per day fell 57%",
             "Revenue per day, days with recorded order values", 1000)]):
        p.add(f"exec_month_{name}", "columnChart", gx(i * 4), y, gw(4), h,
              roles={"Category": [col("dim_date", "month_label")], "Y": [mea(measure)]},
              sort=[(col("dim_date", "month_label"), "Ascending")],
              objects=column_chart("January Highlight Color", units=units, precision=1 if units else 2),
              title=title, subtitle=sub, alt=f"Column chart of {sub.lower()}, January highlighted.")
    p.decision_strip([
        ("Tracking reliability", "Four tracking faults fixed; 30% of orders were credited to the store's own site. "
                                 "Fix GA4 at source."),
        ("Product pages", "3 in 4 product viewers never add to basket, on every device. Investigate, then A/B test."),
        ("Channel credit", "Organic Search gets 40 to 43% under all seven models. Holdout-test Paid Search before cutting."),
        ("Repeat purchasing", "7.5% of customers buy on more than one day. Test a second-purchase offer within two weeks."),
    ])
    p.footer()
    return p


def page_acquisition() -> Page:
    p = light_page("acquisition", "Acquisition & attribution", "Acquisition & attribution",
                   "Where visits come from, and which channels get credit for orders once tracking is corrected.",
                   [MONTH, DEVICE, CHANNEL])
    p.kpi_band([
        *kpis(("Sessions", "Sessions", 1000, 1), ("Engagement rate", "Engagement Rate")),
        {"label": "Orders credited to own site", "measure": "Self-Referral Orders",
         "context": "30% of orders before the fix"},
        {"label": "Organic Search credit (Markov)", "measure": "Organic Search Markov Share",
         "context_measure": "Organic Search Markov CI"},
        {"label": "Orders from a single visit", "measure": "Single-Visit Order Share",
         "context": "Every model agrees on these"},
    ])

    y, h = BAND["primary"]
    p.add("acquisition_countries", "clusteredBarChart", gx(0), y, gw(3), h,
          roles={"Category": [named(col("fct_sessions", "geo_country"), "Country")],
                 "Y": [named(mea("Top 8 Country Share"), "Share of sessions")]},
          sort=[(mea("Top 8 Country Share"), "Descending")],
          objects={**axes(value_axis=False, inner_padding=25, max_margin=40), **labels(precision=1),
                   "legend": props(show=False),
                   "dataPoint": [all_points({"fill": measure_color("Country Highlight Color")})]},
          title="The US brings 44% of visits",
          subtitle="Top 8 of 109 countries · India second at 9%",
          alt="Bar chart of the eight countries with the most sessions; the United States has 44%, India 9%, Canada 7%.")
    cols = [("Sessions", "Sessions", 70), ("Engagement Rate", "Engaged", 60), ("Conversion Rate", "Conversion", 72),
            ("Orders", "Orders", 50), ("Revenue", "Revenue", 72), ("Revenue per Session", "Rev/session", 80)]
    p.add("acquisition_scorecard", "tableEx", gx(3), y, gw(6), h,
          roles={"Values": [named(col("dim_channel", "channel"), "Session channel"),
                            *[named(mea(m), label) for m, label, _ in cols]]},
          sort=[(mea("Sessions"), "Descending")],
          objects={**table_style({"dim_channel.channel": 104, **{f"_Measures.{m}": w for m, _, w in cols}}),
                   "values": table_style()["values"] + [gradient("Conversion Rate")],
                   "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=solid(BORDER), rowPadding=2),},
          title="Session channel scorecard: where visits come from",
          subtitle="Each visit's own channel, so the store's own domain shows as Internal Referral",
          alt="Table of sessions, engagement, conversion, orders and revenue for each session channel.")
    p.add("acquisition_markov", "tableEx", gx(9), y, gw(3), h,
          roles={"Values": [named(col("dim_channel", "channel"), "Channel"), named(mea("Markov Share"), "Share"),
                            named(mea("Markov 95% CI"), "95% interval")]},
          sort=[(mea("Markov Share"), "Descending")],
          objects={**table_style({"dim_channel.channel": 88, "_Measures.Markov Share": 44,
                                  "_Measures.Markov 95% CI": 104}),
                   "total": props(totals=False), "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=solid(BORDER), rowPadding=2),},
          filters=[exclude("dim_channel", "channel", ["Email", "Affiliates", "Unassigned"])],
          title="Data-driven (Markov) credit",
          subtitle="95% bootstrap interval · channels under 1% hidden",
          alt="Table of data-driven attribution share with 95% interval.")

    y, h = BAND["support"]
    small = ["Email", "Affiliates", "Obfuscated"]  # under 2% of orders either way; shown in the scorecard
    p.add("acquisition_fix", "clusteredBarChart", gx(0), y, gw(4), h,
          roles={"Category": [col("dim_channel", "channel")],
                 "Y": [named(mea("Orders (Naive Last Click)"), "As reported"),
                       named(mea("Orders (Corrected Last Click)"), "Corrected")]},
          sort=[(mea("Orders (Naive Last Click)"), "Descending")],
          objects={**axes(value_axis=False, inner_padding=20), **labels(units=1, precision=0),
                   "legend": props(show=False),
                   "dataPoint": [{"properties": {"fill": solid(CONTEXT)},
                                  "selector": {"metadata": "_Measures.Orders (Naive Last Click)"}},
                                 {"properties": {"fill": solid(PRIMARY)},
                                  "selector": {"metadata": "_Measures.Orders (Corrected Last Click)"}}]},
          filters=[exclude("dim_channel", "channel", small)],
          title="870 orders back to real channels, 719 unknown",
          subtitle="Last-click orders as reported (grey) and corrected (blue)",
          alt="Clustered bar chart comparing reported and corrected last-click orders by channel; "
              "Internal Referral falls from 1,589 to zero.")
    p.add("acquisition_models", "pivotTable", gx(4), y, gw(8), h,
          roles={"Rows": [named(col("dim_channel", "channel"), "Channel")],
                 "Columns": [col("dim_attribution_model", "model_label")],
                 "Values": [mea("Attributed Share")]},
          sort=[(mea("Attributed Share"), "Descending")],
          objects={**table_style(), "values": table_style()["values"] + [gradient("Attributed Share")],
                   "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=solid(BORDER),
                                 rowPadding=2),
                   "subTotals": props(columnSubtotals=False, rowSubtotals=False)},
          filters=[exclude("dim_channel", "channel", ["Email", "Affiliates", "Unassigned"])],
          title="Organic Search gets 40 to 43% under all seven models",
          subtitle="Share of order credit by channel and model · darker = more credit · Email and Affiliates "
                   "(under 1%) not shown",
          alt="Heatmap of conversion share by channel and attribution model.")
    p.decision_strip([
        ("Finding", "Organic Search gets 40 to 43% of credit under every model; 30% of orders went to the store itself."),
        ("Evidence", "Seven models agree within 3 points; Markov interval 38.6% to 41.1%; 65% of orders are single-visit."),
        ("Interpretation", "Credit is robust but isn't cause. Markov gives Paid Search 23% more credit than last click."),
        ("Next action", "Exclude own domains in GA4, protect SEO, and holdout-test Paid Search before cutting it."),
    ])
    p.footer(note=" · Markov ignores date filters")
    return p


def page_conversion() -> Page:
    p = light_page("conversion", "Conversion & landing pages", "Conversion & landing pages",
                   "Product pages lose 3 in 4 interested visitors; no device stands out as the problem.",
                   [MONTH, DEVICE, CHANNEL])
    p.kpi_band(kpis(("Session → product view", "Session to View Rate"), ("Product view → cart", "View to Cart Rate"),
                    ("Cart → checkout", "Cart to Checkout Rate"), ("Checkout → purchase", "Checkout to Purchase Rate"),
                    ("Orders per session", "Conversion Rate")))

    y, h = BAND["primary"]
    p.add("conversion_funnel", "funnel", gx(0), y, gw(5), h,
          roles={"Category": [col("dim_funnel_stage", "stage_name")], "Y": [mea("Funnel Sessions")]},
          sort=[(col("dim_funnel_stage", "stage_name"), "Ascending")],
          objects={"dataPoint": props(fill=solid(PRIMARY)), **labels(units=1000, precision=1),
                   "categoryAxis": props(color=solid(INK_2), fontSize=9)},
          title="Only 1.35% of sessions end in a purchase",
          subtitle="Sessions reaching each step (each step's base is the step before) · 70 days with working cart tracking",
          alt="Funnel: 284k sessions, 59k product views, 15k add to cart, 8k checkout, 3.8k purchase.")
    p.add("conversion_device", "tableEx", gx(5), y, gw(7), h,
          roles={"Values": [named(col("dim_funnel_stage", "stage_name"), "Step reached"),
                            named(mea("Desktop Step Rate"), "Desktop"), named(mea("Mobile Step Rate"), "Mobile"),
                            named(mea("Mobile Minus Desktop"), "Mobile − desktop"),
                            named(mea("Mobile Minus Desktop CI"), "95% interval")]},
          sort=[(col("dim_funnel_stage", "stage_name"), "Ascending")],
          objects={**table_style(), "total": props(totals=False)},
          filters=[exclude("dim_funnel_stage", "stage_name", ["Session"])],
          title="No clear difference between mobile and desktop at any step",
          subtitle="% of the previous step that continued · every interval includes zero",
          alt="Table of step conversion for desktop and mobile with the difference and its 95% interval.")

    y, h = BAND["support"]
    p.add("conversion_landing", "tableEx", gx(0), y, gw(8), h,
          roles={"Values": [named(col("fct_sessions", "landing_page_group"), "Landing page"),
                            named(mea("Sessions"), "Sessions"), named(mea("Landing Session Share"), "Share of visits"),
                            named(mea("Session Purchase Rate"), "Purchase rate"),
                            named(mea("Session Purchase Rate CI"), "95% interval")]},
          sort=[(mea("Sessions"), "Descending")],
          objects={**table_style({"fct_sessions.landing_page_group": 330, "_Measures.Sessions": 80,
                                  "_Measures.Landing Session Share": 80, "_Measures.Session Purchase Rate": 90,
                                  "_Measures.Session Purchase Rate CI": 130}),
                   "total": props(totals=False), "values": table_style()["values"] + [gradient("Session Purchase Rate")]},
          filters=[exclude("fct_sessions", "landing_page_group", ["Other pages", "(not recorded)"])],
          title="Four big entry pages bring 29% of visits but 7% of purchases",
          subtitle="Landing pages with 1,000+ sessions · site rate 1.45% · darker = higher purchase rate",
          alt="Table of landing pages with sessions, purchases, purchase rate and 95% interval.")
    p.note("conversion_explain", 8, 4, "support", "Why might those pages convert poorly?", [
        "Observed: Apparel, YouTube shop, Dino Game Tee and store.html sit well below the site rate.",
        "Possible: low purchase intent (the Dino Game Tee draws searches for Chrome's offline game).",
        "Possible: untagged links (63% of Apparel landings are 'Direct').",
        "Possible: page friction; not yet tested.",
        "→ Check each page's traffic mix, then A/B test the Apparel page first.",
    ])
    p.decision_strip([
        ("Finding", "3 in 4 product viewers never add to basket; no clear device-level difference was detected."),
        ("Evidence", "View to cart 25.7% on 59k product-view sessions; every mobile-minus-desktop interval includes zero."),
        ("Interpretation", "Product and entry pages leak on every device; weak entry pages may mean low intent, "
                           "not bad design."),
        ("Next action", "Check traffic mix on the weak entry pages, A/B test the product page, then the checkout."),
    ])
    p.footer()
    return p


def page_customers() -> Page:
    p = light_page("customers", "Customers & retention", "Customers & retention",
                   "Most customers buy once; the few who return do it within two weeks.",
                   [("month", col("dim_date", "month_label"), "First purchase month"),
                    ("device", col("dim_device", "device_category"), "First device"),
                    ("channel", col("dim_channel", "channel"), "First channel")])
    p.kpi_band([
        {"label": "Customers", "measure": "Customers", "context": "Browsers with at least one order"},
        {"label": "Bought on 2+ days", "measure": "Repeat Customer Rate", "context": "Most customers buy once"},
        {"label": "Median spend per customer", "measure": "Median Customer Spend", "context": "Half spent less than this"},
        {"label": "Revenue from big one-off spenders", "measure": "Big Spender Revenue Share", "color": PRIMARY_STRONG,
         "context": "From 15% of customers"},
        {"label": "Repeat buyers back within 2 weeks", "measure": "Back Within 14 Days",
         "context": "The window for a second order"},
    ])
    segment = named(col("dim_customers", "rfm_segment"), "Segment")

    y, h = BAND["primary"]
    p.add("customers_segments", "clusteredBarChart", gx(0), y, gw(7), h,
          roles={"Category": [segment], "Y": [mea("Share of Customers"), mea("Share of Revenue")],
                 "Tooltips": [mea("Customers")]},
          sort=[(mea("Share of Revenue"), "Descending")],
          objects={**axes(value_axis=False, inner_padding=30), **labels(),
                   "legend": props(show=True, position="Top", fontSize=8, labelColor=solid(INK_2), showTitle=False),
                   "dataPoint": [{"properties": {"fill": solid(CONTEXT)},
                                  "selector": {"metadata": "_Measures.Share of Customers"}},
                                 {"properties": {"fill": solid(PRIMARY)},
                                  "selector": {"metadata": "_Measures.Share of Revenue"}}]},
          title="15% of customers, the big one-off spenders, bring in 41% of revenue",
          subtitle="Share of customers (grey) and of revenue (blue) by segment · counts in the table below",
          alt="Clustered bar chart of each segment's share of customers and of revenue.")
    p.add("customers_repeat_window", "columnChart", gx(7), y, gw(5), h,
          roles={"Category": [named(col("dim_customers", "repeat_window"), "Came back")],
                 "Y": [mea("Repeat Buyers")]},
          sort=[(col("dim_customers", "repeat_window"), "Ascending")],
          objects=column_chart(units=1, precision=0),
          title="6 in 10 repeat buyers come back within two weeks",
          subtitle="Repeat buyers (count) by days from first to second buying day",
          alt="Column chart of repeat buyers by time to second purchase; the first week is the largest group.")

    y, h = BAND["support"]
    p.add("customers_cohorts", "pivotTable", gx(0), y, gw(5), h,
          roles={"Rows": [named(col("dim_date", "month_label"), "First purchase")],
                 "Values": [named(mea("Repeat Within 7 Days"), "7 days"),
                            named(mea("Repeat Within 14 Days"), "14 days"),
                            named(mea("Repeat Within 30 Days"), "30 days"),
                            named(mea("Eligible Customers 30 Days"), "Followed 30 days")]},
          objects={**table_style({"_Measures.Repeat Within 7 Days": 72, "_Measures.Repeat Within 14 Days": 72,
                                  "_Measures.Repeat Within 30 Days": 72, "_Measures.Eligible Customers 30 Days": 96}),
                   "subTotals": props(rowSubtotals=False, columnSubtotals=False),
                   "values": table_style()["values"] + [gradient("Repeat Within 30 Days")]},
          title="December buyers matched November's in week one, then fell behind",
          subtitle="Bought again within N days · blank where fewer than 100 customers could be followed that long",
          alt="Cohort grid of repeat purchase within 7, 14 and 30 days by first-purchase month.")
    p.add("customers_actions", "tableEx", gx(5), y, gw(7), h,
          roles={"Values": [segment, mea("Customers"), named(mea("Share of Customers"), "Customer share"),
                            named(mea("Share of Revenue"), "Revenue share"),
                            named(mea("Average Customer Spend"), "Avg spend"),
                            named(mea("Segment Action"), "Suggested action")]},
          sort=[(mea("Share of Revenue"), "Descending")],
          objects={**table_style({"dim_customers.rfm_segment": 140, "_Measures.Customers": 72,
                                  "_Measures.Share of Customers": 80, "_Measures.Share of Revenue": 80,
                                  "_Measures.Average Customer Spend": 64, "_Measures.Segment Action": 196}),
                   "total": props(totals=False)},
          title="What to do with each segment",
          subtitle="Segments from recency, spend and number of buying days (docs/customers.md)",
          alt="Table of segments with customers, shares, average spend and a suggested action.")
    p.decision_strip([
        ("Finding", "15% of customers (679) bring 41% of revenue, and only 7.5% bought on more than one day."),
        ("Evidence", "6 in 10 repeat buyers return within 14 days; 30-day repeat 8.8% (Nov, 1,532) vs 5.7% (Dec, 1,870)."),
        ("Interpretation", "One-off buys dominate and holiday buyers rarely return; browser-level IDs understate loyalty."),
        ("Next action", "Test a second-purchase offer within two weeks of a first order against a holdout group."),
    ])
    p.footer(note=" · customers are browsers; filters use the first purchase")
    return p


def page_orders() -> Page:
    p = light_page("orders", "Orders & products", "Orders & products",
                   "A typical order is $46; bigger baskets go with bigger orders.", [MONTH, DEVICE, CHANNEL])
    p.kpi_band([
        {"label": "Orders with recorded values", "measure": "Orders (Clean Value Days)", "context": "26 to 31 Jan excluded"},
        {"label": "Median order value", "measure": "Median Order Value", "context": "A typical order"},
        {"label": "Average order value", "measure": "Mean Order Value", "context": "Pulled up by large orders"},
        {"label": "Orders with several products", "measure": "Multi-Product Order Share", "context": "Of orders with item detail"},
        {"label": "Revenue from the top 10% of orders", "measure": "Top Decile Order Revenue Share",
         "context": "Revenue is broad, not a few huge orders"},
    ])

    y, h = BAND["primary"]
    p.add("orders_distribution", "columnChart", gx(0), y, gw(7), h,
          roles={"Category": [named(col("fct_orders", "order_value_band"), "Order value")],
                 "Y": [named(mea("Orders (Clean Value Days)"), "Orders")]},
          sort=[(col("fct_orders", "order_value_band"), "Ascending")],
          objects=column_chart(units=1, precision=0),
          title="Most orders are between $25 and $100",
          subtitle="Orders by value band · median $46, mean $67 · excludes 26 to 31 Jan (values missing)",
          alt="Column chart of orders by value band; the $50 to $100 band is largest.")
    p.add("orders_basket", "clusteredBarChart", gx(7), y, gw(5), h,
          roles={"Category": [named(col("fct_orders", "basket_type"), "Basket")],
                 "Y": [mea("Median Order Value"), mea("Mean Order Value")], "Tooltips": [mea("Orders (Clean Value Days)")]},
          sort=[(mea("Median Order Value"), "Descending")],
          objects={**axes(value_axis=False, inner_padding=30), **labels(units=1, precision=0),
                   "legend": props(show=True, position="Top", fontSize=8, labelColor=solid(INK_2), showTitle=False),
                   "dataPoint": [{"properties": {"fill": solid(PRIMARY)}, "selector": {"metadata": "_Measures.Median Order Value"}},
                                 {"properties": {"fill": solid(CONTEXT)}, "selector": {"metadata": "_Measures.Mean Order Value"}}]},
          filters=[exclude("fct_orders", "basket_type", ["No item detail"])],
          title="Orders with several products are worth more than twice single-product ones",
          subtitle="Median (blue) and mean (grey) order value · an association, not proof that bundles raise value",
          alt="Bar chart of median and mean order value for one-product and several-product orders.")

    y, h = BAND["support"]
    p.add("orders_products", "tableEx", gx(0), y, gw(5), h,
          roles={"Values": [named(col("fct_order_items", "item_name"), "Product"), named(mea("Product Orders"), "Orders"),
                            named(mea("Units Sold"), "Units"), named(mea("Product Revenue"), "Revenue"),
                            named(mea("Product Revenue Share"), "Share")]},
          sort=[(mea("Product Revenue"), "Descending")],
          objects={**table_style(), "total": props(totals=False)},
          title="36 of 396 products make half of product revenue",
          subtitle="Products ranked by revenue · scroll for all",
          alt="Table of products ranked by revenue with orders, units and share.")
    p.add("orders_categories", "barChart", gx(5), y, gw(3), h,
          roles={"Category": [named(col("fct_order_items", "item_category"), "Category")], "Y": [mea("Product Revenue Share")]},
          sort=[(mea("Product Revenue Share"), "Descending")],
          objects=bar_chart("Apparel Highlight Color", units=0, precision=0),
          filters=[exclude("fct_order_items", "item_category", ["", "(not set)"])],
          title="Apparel is 47% of product revenue",
          subtitle="Share of product revenue by category",
          alt="Bar chart of product revenue share by category; Apparel highlighted.")
    p.add("orders_pairs", "tableEx", gx(8), y, gw(4), h,
          roles={"Values": [named(col("mart_product_pairs", "product_a"), "Product"),
                            named(col("mart_product_pairs", "product_b"), "Bought with"),
                            named(mea("Pair Orders"), "Orders"), named(mea("Pair Lift"), "Lift")]},
          sort=[(mea("Pair Orders"), "Descending")],
          objects={**table_style({"mart_product_pairs.product_a": 124, "mart_product_pairs.product_b": 124,
                                  "_Measures.Pair Orders": 48, "_Measures.Pair Lift": 40}),
                   "total": props(totals=False)},
          title="Only five pairs sell together often, all variants of one product",
          subtitle="Pairs in 30+ orders · lift = times more often than chance · full period",
          alt="Table of the product pairs bought together in 30 or more orders, with lift.")
    p.decision_strip([
        ("Finding", "A typical order is $46; multi-product orders have a median of $63 against $25."),
        ("Evidence", "5,028 orders with values; 59% contain several products; only five pairs appear in 30+ orders."),
        ("Interpretation", "Bigger baskets go with bigger orders (an association). Frequent pairs are variants of one item."),
        ("Next action", "Test a free-shipping threshold just above the median and multi-colour sets against a control group."),
    ])
    p.footer()
    return p


# ---- dark "Night" overview (product-style look, design-system discipline) --------------------------------
# 1440x1000 canvas: 240px sidebar + 4-column content grid (276px columns, 16px gutters) starting at x=264.
# Visual names containing "_ovl" are deliberately layered on top of another visual.

def dx(col_: int) -> int:
    return 264 + col_ * 292


def dw(span: int) -> int:
    return span * 276 + (span - 1) * 16


def no_axes() -> dict:
    return {"categoryAxis": props(show=False), "valueAxis": props(show=False, gridlineShow=False),
            "legend": props(show=False)}


def sparkline(measure: str, color: str) -> dict:
    """Area-shaded trend line with no axes, used behind a KPI value."""
    return {**no_axes(), **labels(show=False),
            "lineStyles": props(strokeWidth=2, showMarker=False, areaShow=True),
            "dataPoint": [{"properties": {"fill": solid(color)}, "selector": {"metadata": f"_Measures.{measure}"}},
                          {"properties": {"transparency": lit(75)}}]}


def series_fill(colors: dict[str, str]) -> list[dict]:
    return [{"properties": {"fill": solid(c)}, "selector": {"metadata": f"_Measures.{m}"}} for m, c in colors.items()]


def overlay_card(p: Page, name: str, x, y, w, h, measure: str, size: int, color: dict, label: str | None = None):
    """Transparent card layered on another visual (KPI value, ring centre)."""
    container = {"background": props(show=False), "padding": props(top=0, bottom=0, left=0, right=0)}
    container["title"] = (props(show=True, text=label, fontSize=10, fontColor=solid(INK_2), fontFamily=raw(REGULAR))
                          if label else props(show=False))
    p.add(name, "card", x, y, w, h, roles={"Values": [mea(measure)]},
          objects={"labels": props(fontSize=size, color=color, fontFamily=raw(SEMIBOLD), labelDisplayUnits=1),
                   "categoryLabels": props(show=False)},
          container=container)


def page_dark_overview() -> Page:
    p = Page("night_overview", "Overview", width=1440, height=1000)

    # Sidebar: brand, filters, reading guide (the mockup's nav, but every element does something)
    p.add("sidebar_bg", "textbox", 0, 0, 240, 1000, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [text_run("GA4 Pulse", 20, INK, bold=True)]},
        {"textRuns": [text_run("Google Merchandise Store", 9, INK_2)]},
        {"textRuns": [text_run("Nov 2020 – Jan 2021", 9, MUTED)]}]}}]},
        container={"background": props(show=True, color=solid(SIDEBAR)), "border": props(show=False, radius=0),
                   "padding": props(top=28, bottom=0, left=24, right=24)})
    for i, (name, field, label, mode) in enumerate([
            ("date", col("dim_date", "date"), "Date range", "Between"),
            ("device", col("dim_device", "device_category"), "Device", "Dropdown"),
            ("channel", col("dim_channel", "channel"), "Channel", "Dropdown")]):
        p.add(f"sidebar_{name}_ovl", "slicer", 16, 120 + i * 88, 208, 76, roles={"Values": [field]},
              objects={"data": props(mode=mode), "header": props(show=False),
                       "items": props(fontColor=solid(INK), fontSize=10)},
              container={"background": props(show=False), "padding": props(top=0, bottom=0, left=8, right=8),
                         "title": props(show=True, text=label, fontSize=9, fontColor=solid(INK_2),
                                        fontFamily=raw(REGULAR))})
    p.add("sidebar_guide_ovl", "textbox", 16, 800, 208, 176, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [text_run("How to read this", 10, INK, bold=True)]},
        {"textRuns": [text_run("Pink marks the one thing to look at.", 9, INK_2)]},
        {"textRuns": [text_run("▲▼ compare with the previous period of the same length.", 9, INK_2)]},
        {"textRuns": [text_run("Orders deduplicated; self-referrals removed; funnel skips 22 days with a broken cart tag; order values missing 26 to 31 Jan. Source: GA4 public sample.", 8, MUTED)]},
    ]}}]}, container=transparent())

    # Header
    p.add("night_header", "textbox", dx(0), 20, dw(4), 60, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [text_run("Overview", 22, INK, bold=True)]},
        {"textRuns": [text_run("December was the peak month; "
                               "in January conversion fell by almost half.", 11, INK_2)]}]}}]},
        container={**transparent(), "padding": props(top=0, bottom=0, left=0, right=0)})

    # KPI cards: label + value + change on the left, area-shaded trend behind on the right
    kpis = [("Revenue", "Revenue"), ("Orders", "Orders"), ("Sessions", "Sessions"),
            ("Conversion rate", "Conversion Rate")]
    for i, (label, m) in enumerate(kpis):
        x, y = dx(i), 96
        p.add(f"kpi{i}_spark", "lineChart", x, y, dw(1), 120,
              roles={"Category": [col("dim_date", "date")], "Y": [mea(m)]},
              sort=[(col("dim_date", "date"), "Ascending")],
              objects=sparkline(m, PRIMARY),
              container={"title": props(show=False), "padding": props(top=56, bottom=8, left=152, right=8)},
              alt=f"{label} trend over the selected period")
        overlay_card(p, f"kpi{i}_value_ovl", x + 16, y + 12, 128, 64, m, 22, solid(INK), label=label)
        overlay_card(p, f"kpi{i}_change_ovl", x + 16, y + 78, 128, 34, f"{m} Change", 8,
                     measure_color(f"{m} Change Color Dark"))

    # Row 3: traffic trend (2 cols), weekday pattern (1 col), countries (1 col, two rows tall)
    p.add("night_traffic", "lineChart", dx(0), 232, dw(2), 296,
          roles={"Category": [col("dim_date", "date")], "Y": [mea("Organic Search Sessions"), mea("Direct Sessions")]},
          sort=[(col("dim_date", "date"), "Ascending")],
          objects={**axes(), **labels(show=False),
                   "legend": props(show=True, position="Top", fontSize=8, labelColor=solid(INK_2), showTitle=False),
                   "lineStyles": props(strokeWidth=2, showMarker=False, areaShow=True),
                   "dataPoint": series_fill({"Organic Search Sessions": PRIMARY, "Direct Sessions": TEAL})
                   + [{"properties": {"transparency": lit(80)}}]},
          title="Direct and Organic Search bring two-thirds of all visits",
          subtitle="Daily sessions · both climb into December",
          alt="Area chart of daily sessions from Direct and Organic Search, November to January.")
    p.add("night_weekday", "barChart", dx(2), 232, dw(1), 296,
          roles={"Category": [col("dim_date", "day_name")], "Y": [mea("Revenue per Day")]},
          sort=[(col("dim_date", "day_name"), "Ascending")],
          objects=bar_chart("Sunday Highlight Color Dark", units=1000, precision=1),
          title="Sundays earn less than half a Friday's revenue",
          subtitle="Average revenue per day, by weekday",
          alt="Bar chart of average daily revenue by weekday; Sunday highlighted as lowest.")
    p.add("night_countries", "tableEx", dx(3), 232, dw(1), 528,
          roles={"Values": [named(col("fct_sessions", "geo_country"), "Country"), mea("Sessions"),
                            named(mea("Session Share"), "Share")]},
          sort=[(mea("Sessions"), "Descending")],
          objects={**table_style(), "total": props(totals=False)},
          title="The US brings 44% of visits; India is #2 at 9%",
          subtitle="Sessions by country · scroll for all 109",
          alt="Table of sessions and share of sessions by country.")

    # Row 4: funnel rings (2 cols) + device split (1 col)
    p.add("night_rings_bg", "textbox", dx(0), 544, dw(2), 216, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [text_run("Only 1 in 4 product viewers adds to basket", 11, INK, bold=True)]},
        {"textRuns": [text_run("% of the previous step that continued · excludes 22 days with a broken cart tag", 9, INK_2)]}]}}]},
        container={"background": props(show=True, color=solid(CARD))})
    rings = [("Session → product view", "Session to View Rate"), ("Product view → cart", "View to Cart Rate"),
             ("Cart → checkout", "Cart to Checkout Rate"), ("Checkout → purchase", "Checkout to Purchase Rate")]
    ring_w = (dw(2) - 32) // 4
    for i, (label, m) in enumerate(rings):
        x = dx(0) + 16 + i * ring_w
        color = ACCENT if m == "View to Cart Rate" else PRIMARY
        p.add(f"ring{i}_ovl", "donutChart", x, 596, ring_w, 128,
              roles={"Y": [mea(m), mea(f"{m} Remainder")]},
              objects={"legend": props(show=False), "labels": props(show=False),
                       "slices": props(innerRadiusRatio=78),
                       "dataPoint": series_fill({m: color, f"{m} Remainder": TRACK})},
              container={"background": props(show=False), "title": props(show=False),
                         "padding": props(top=0, bottom=0, left=0, right=0)},
              alt=f"{label}: step conversion ring")
        overlay_card(p, f"ring{i}_value_ovl", x + (ring_w - 80) // 2, 642, 80, 36, m, 14, solid(INK))
        p.add(f"ring{i}_label_ovl", "textbox", x, 726, ring_w, 28, objects={"general": [{"properties": {
            "paragraphs": [{"textRuns": [text_run(label, 9, INK_2)], "horizontalTextAlignment": "center"}]}}]},
            container=transparent())
    p.add("night_device", "donutChart", dx(2), 544, dw(1), 216,
          roles={"Category": [col("dim_device", "device_category")], "Y": [mea("Sessions")]},
          objects={"legend": props(show=True, position="Bottom", fontSize=8, labelColor=solid(INK_2), showTitle=False),
                   "labels": props(show=True, labelStyle="Percent of total", color=solid(INK_2), fontSize=8,
                                   labelPrecision=0),
                   "slices": props(innerRadiusRatio=70)},
          title="Desktop drives 58% of visits", subtitle="Sessions by device",
          alt="Donut chart of sessions by device: desktop, mobile, tablet.")

    # Row 5: channel conversion (1 col), monthly mix (2 cols), top products (1 col)
    p.add("night_channel_cvr", "tableEx", dx(3), 776, dw(1), 200,
          roles={"Values": [named(col("dim_channel", "channel"), "Channel"), named(mea("Conversion Rate"), "Conversion")]},
          sort=[(mea("Conversion Rate"), "Descending")],
          objects={**table_style(), "total": props(totals=False)}, filters=[exclude("dim_channel", "channel", ["Internal Referral", "Unassigned"])],
          title="Referral converts best at scale (4.1%)", subtitle="Conversion rate by channel",
          alt="Table of conversion rate and orders by channel.")
    p.add("night_monthly", "clusteredColumnChart", dx(2), 776, dw(1), 200,
          roles={"Category": [col("dim_date", "month_label")],
                 "Y": [mea("Organic Search Sessions"), mea("Direct Sessions"), mea("Other Sessions")]},
          sort=[(col("dim_date", "month_label"), "Ascending")],
          objects={**axes(inner_padding=30), **labels(show=False),
                   "legend": props(show=True, position="Top", fontSize=8, labelColor=solid(INK_2), showTitle=False),
                   "dataPoint": series_fill({"Organic Search Sessions": PRIMARY, "Direct Sessions": TEAL,
                                             "Other Sessions": CONTEXT})},
          title="Direct grew fastest into December", subtitle="Sessions by month · Direct +36%",
          alt="Clustered column chart of monthly sessions for Organic Search, Direct and other channels.")
    p.add("night_products", "tableEx", dx(0), 776, dw(2), 200,
          roles={"Values": [named(col("fct_order_items", "item_name"), "Product"), named(mea("Product Revenue"), "Revenue"),
                            named(mea("Units Sold"), "Units")]},
          sort=[(mea("Product Revenue"), "Descending")],
          objects={**table_style(), "total": props(totals=False)},
          title="Clothing fills all top-8 best sellers", subtitle="Revenue and units by product (deduplicated orders)",
          alt="Table of products ranked by revenue.")
    return p


def write_light_theme() -> None:
    """dashboard/theme.json from design/tokens.json, so the dashboard can't drift from the charts and documents."""
    font, semibold = TOKENS["font"]["family"], TOKENS["font"]["family.semibold"]
    theme = {
        "$schema": "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/"
                   "Report%20Theme%20JSON%20Schema/reportThemeSchema-2.157.json",
        "name": BRAND,
        "dataColors": _T["categorical"],
        "background": CARD, "secondaryBackground": PAGE_BG, "foreground": INK,
        "foregroundNeutralSecondary": INK_2, "foregroundNeutralTertiary": MUTED, "foregroundSelected": PRIMARY_STRONG,
        "disabledText": _T["sidebar.muted"], "tableAccent": PRIMARY, "accent": PRIMARY,
        "good": POSITIVE, "neutral": _T["status.warning.text"], "bad": NEGATIVE,
        "maximum": HEAT_MAX, "center": SECONDARY, "minimum": HEAT_MIN, "null": BORDER,
        "textClasses": {
            "largeTitle": {"fontSize": 20, "fontFace": semibold, "color": INK},
            "callout": {"fontSize": 26, "fontFace": font, "color": INK},
            "title": {"fontSize": 12, "fontFace": semibold, "color": INK},
            "header": {"fontSize": 10, "fontFace": semibold, "color": INK},
            "label": {"fontSize": 9, "fontFace": font, "color": INK_2},
            "smallLabel": {"fontSize": 8, "fontFace": font, "color": MUTED},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": {"solid": {"color": CARD}}, "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": BORDER}}, "radius": TOKENS["radius"]["card"]}],
                "dropShadow": [{"show": False}],
                "padding": [{"top": 16, "bottom": 16, "left": 16, "right": 16}],
                "title": [{"show": True, "fontFamily": semibold, "fontSize": 12, "fontColor": {"solid": {"color": INK}},
                           "alignment": "left", "titleWrap": True}],
                "subTitle": [{"fontFamily": font, "fontSize": 9, "fontColor": {"solid": {"color": INK_2}},
                              "alignment": "left", "titleWrap": True}],
                "spacing": [{"customizeSpacing": True, "spaceBelowTitle": 4, "spaceBelowSubTitle": 8,
                             "spaceBelowTitleArea": 12}],
            }},
            "page": {"*": {
                "background": [{"color": {"solid": {"color": PAGE_BG}}, "transparency": 0}],
                "outspace": [{"color": {"solid": {"color": PAGE_BG}}, "transparency": 0}],
            }},
        },
    }
    write_json(PBI_DIR / "theme.json", theme)


def build_report(report_dir: Path, pbip_name: str, pages: list, theme_file: str) -> None:
    d = report_dir / "definition"
    write_json(report_dir / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(d / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    theme_name = "MarketingAnalyticsTheme.json"
    write_json(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {
                "visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"}, "type": "SharedResources"},
            "customTheme": {"name": theme_name, "reportVersionAtImport": {
                "visual": "2.1.0", "report": "2.1.0", "page": "2.0.0"}, "type": "RegisteredResources"},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": theme_name, "path": theme_name, "type": "CustomTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })
    static = report_dir / "StaticResources"
    (static / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    (static / "RegisteredResources").mkdir(parents=True, exist_ok=True)
    shutil.copy(PBI_DIR / "_base" / "CY24SU10.json", static / "SharedResources" / "BaseThemes" / "CY24SU10.json")
    shutil.copy(PBI_DIR / theme_file, static / "RegisteredResources" / theme_name)

    write_json(d / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name})
    for p in pages:
        page = {"$schema": PAGE_SCHEMA, "name": p.name, "displayName": p.display, "displayOption": "FitToPage",
                "height": p.height, "width": p.width}
        if p.interactions:
            page["visualInteractions"] = p.interactions
        write_json(d / "pages" / p.name / "page.json", page)
        for v in p.visuals:
            write_json(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)

    write_json(PBI_DIR / f"{pbip_name}.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": report_dir.name}}],
        "settings": {"enableAutoRecovery": True}})


# =====================================================================================
# VALIDATION
# =====================================================================================

def REPORTS_GLOB():
    for rd in PBI_DIR.glob("*.Report"):
        yield from rd.rglob("*.json")
        yield from rd.glob("*.pbir")


def validate_report() -> int:
    """Validate every report JSON file against the Microsoft schema named in its $schema."""
    import jsonschema
    import requests
    from referencing import Registry, Resource

    cache: dict[str, dict] = {}

    def fetch(uri: str) -> dict:
        if uri not in cache:
            url = uri.replace("https://developer.microsoft.com/json-schemas/",
                              "https://raw.githubusercontent.com/microsoft/json-schemas/main/")
            cache[uri] = requests.get(url, timeout=30).json()
        return cache[uri]

    registry = Registry(retrieve=lambda uri: Resource.from_contents(fetch(uri)))
    errors = 0
    files = [*REPORTS_GLOB(), *PBI_DIR.glob("*.pbip"), SM_DIR / "definition.pbism"]
    for f in files:
        if "StaticResources" in f.parts:
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        schema_uri = doc.get("$schema")
        if not schema_uri:
            continue
        validator = jsonschema.Draft7Validator(fetch(schema_uri), registry=registry) \
            if "draft-07" in fetch(schema_uri).get("$schema", "") else \
            jsonschema.validators.validator_for(fetch(schema_uri))(fetch(schema_uri), registry=registry)
        for err in validator.iter_errors(doc):
            errors += 1
            print(f"  {f.relative_to(PBI_DIR)}: {'/'.join(map(str, err.absolute_path))}: {err.message[:200]}")
    print(f"Validated {len(files)} files: {errors} error(s)")
    return errors


def check_references_and_layout() -> int:
    """Checks the schemas can't do: every referenced measure exists, and visuals stay on the canvas without overlap."""
    errors = 0
    names = {m[0] for m in MEASURES}
    for name, _, _, dax in MEASURES:
        for ref_name in re.findall(r"(?<![\w\]'])\[([^\]]+)\]", dax):
            if ref_name not in names:
                errors += 1
                print(f"  measure [{name}] references unknown measure [{ref_name}]")
    for vfile in PBI_DIR.glob("*.Report/**/visual.json"):
        text = vfile.read_text(encoding="utf-8")
        for m in re.findall(r'"Entity": "_Measures"\s*},\s*"Property": "([^"]+)"', text):
            if m not in names:
                errors += 1
                print(f"  {vfile.parent.name}: unknown measure [{m}]")
    for page_dir in PBI_DIR.glob("*.Report/definition/pages/*"):
        if not page_dir.is_dir():
            continue
        page_meta = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
        page_w, page_h = page_meta["width"], page_meta["height"]
        boxes = []
        for vfile in page_dir.rglob("visual.json"):
            pos = json.loads(vfile.read_text(encoding="utf-8"))["position"]
            x, y, w, h = pos["x"], pos["y"], pos["width"], pos["height"]
            if x < 0 or y < 0 or x + w > page_w or y + h > page_h:
                errors += 1
                print(f"  {page_dir.name}/{vfile.parent.name}: off canvas ({x},{y},{w},{h})")
            boxes.append((vfile.parent.name, x, y, x + w, y + h))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if "_ovl" in a[0] or "_ovl" in b[0]:
                    continue  # deliberate layering (e.g. value card on top of its sparkline)
                if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                    errors += 1
                    print(f"  {page_dir.name}: {a[0]} overlaps {b[0]}")
    print(f"Reference & layout checks: {errors} error(s)")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    for d in (SM_DIR / "definition", RP_DIR / "definition", DARK_DIR / "definition"):
        if d.exists():
            shutil.rmtree(d)  # regenerate cleanly; .pbi caches and local settings are kept
    build_semantic_model()
    write_light_theme()
    build_report(RP_DIR, NAME, [page_executive(), page_acquisition(), page_conversion(), page_customers(), page_orders()],
                 "theme.json")
    with palette(DARK_PALETTE):
        build_report(DARK_DIR, f"{NAME}Dark", [page_dark_overview()], "theme_dark.json")
    write_measures_reference()
    write_kpi_dictionary()
    print(f"Wrote {PBI_DIR / (NAME + '.pbip')}  ({len(MEASURES)} measures, {len(TABLES) + 1} tables, "
          f"{len(RELATIONSHIPS)} relationships)")
    if args.validate:
        raise SystemExit(1 if (validate_report() + check_references_and_layout()) else 0)


if __name__ == "__main__":
    main()
