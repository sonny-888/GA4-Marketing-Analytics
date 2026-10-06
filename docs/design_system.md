# Design system: Merch Store Analytics Review

One design system for every output of this project: the Power BI report, the Python and R charts, the PDF report, the review report and the slide deck. Part 1 is the research behind it; Part 2 is the system itself.

**Implementation:** [`design/tokens.json`](../design/tokens.json) holds every colour and font. `python/marketing_analytics/style.py`, `r/R/style.R` and `dashboard/build_pbip.py` (which also writes `dashboard/theme.json`) read it; the report and deck CSS use the same values. The dark overview report keeps its own theme, `dashboard/theme_dark.json`.

---

## Part 1 · Research

### 1.1 Sources and how they were used

| Reference | Access | What I took from it |
|---|---|---|
| Apple HIG: *Charts* | Read in full (official JSON feed) | Chart anatomy, axes, descriptive titles, hierarchy, colour, accessibility, interaction |
| Datawrapper: *Text in data visualisations*, *Colours for data vis style guides*, *Which colour scale to use* | Read in full | Direct labels, font-size limits, alignment, number formats, palette strategy |
| Google Material Design 3 | Site is JavaScript-only, so not readable here; used its published foundations from prior knowledge | 4/8-point spacing grid, type scale, tonal surfaces instead of shadows, state colours, 4.5:1 contrast |
| Tableau Public / Flourish | Interactive galleries that can't be read as text; used general knowledge of the patterns that win there | Guided "headline → chart → annotation" layouts, restrained highlight colour, small multiples |
| Google Design ([design.google](https://design.google/about)), Material Design 3 theming ([codelab](https://developer.android.com/codelabs/m3-design-theming)), Google's accessible colour codelab | Prior knowledge plus the published guidance | Role-based colour tokens, a type scale, neutral surfaces with one accent, contrast checks, reusable components |
| McKinsey Insights / BCG Publications | Timed out or blocked; used well-documented consulting conventions | Action titles, one message per exhibit, numbered exhibits, a source line on every chart |

Where a principle comes from prior knowledge rather than a page read here, the table says so. It's worth checking those references yourself before quoting them in an interview.

### 1.2 What each reference teaches, and what Power BI can actually do

**Apple: hierarchy and restraint** (read directly)
- *"Typically, you want the data itself to be most prominent, while letting the descriptions and axes provide additional context without competing with the data."*
  - **Power BI:** light grey axis labels, dotted light gridlines, no axis titles.
- *Write titles that summarise the main message so people grasp it quickly.*
  - **Power BI:** a visual title plus a subtitle, both supported.
- *Too many gridlines overwhelm, too few make values hard to estimate. Use fewer gridlines and lighter labels when people can inspect values interactively.*
  - **Power BI:** value-axis gridlines only, dotted; tooltips provide the exact values.
- *Prefer familiar tick sequences (0, 5, 10).*
  - **Power BI:** this happens automatically, as long as the axis isn't forced to odd bounds.
- *Bars start at zero; lines may use a dynamic range.*
  - **Power BI:** the bar axis starts at 0 by default. For line charts, leave the axis on auto.
- *Don't rely on colour alone. Separate adjacent coloured areas.*
  - **Power BI:** use direct labels and a 2px gap between bars (inner padding).
- *Don't require interaction to reveal critical information.*
  - **Power BI:** the key number must be visible without hovering. Tooltips are for detail only.
- *Align charts on a shared leading edge.*
  - **Power BI:** a common left edge for all visuals on the grid.

**Datawrapper: text is a design element** (read directly)
- *Label directly. Remove the colour key where possible.*
  - **Power BI:** turn the legend off and use line-chart series labels and data labels instead.
- *Limit font sizes: two levels for labels and annotations (e.g. 12px grey and 14px black). Emphasise with bold.*
- *Don't centre-align text. Don't rotate axis labels; use a bar chart instead.*
- *Be conversational first and precise later:* the title states the message, and the precise definition goes in the subtitle or footnote.
- *Don't add unnecessary precision (12.8k rather than 12,831), but repeat the units.*
- *Palette approach:* the "minimalists" (a few hues, with grey for everything else) are the most robust. Keep the colour order fixed.

**Material Design: system thinking** (prior knowledge)
- An 8-point spacing scale, a named type scale, and tonal surfaces (contrast instead of shadows).
- 4.5:1 contrast for text and 3:1 for graphical marks.
- **Power BI:** all positions use multiples of 8, and the theme's text classes act as the type scale.

**Tableau / Flourish: guided analytics** (prior knowledge)
- Each view answers one question.
- One highlight colour against grey context.
- Small multiples instead of spaghetti charts with many overlapping lines.
- **Power BI:** small multiples are native on bar, column and line charts.

**McKinsey / BCG: storytelling** (prior knowledge)
- An action title on every exhibit: a full sentence stating the "so what".
- One message per chart.
- Source and notes in small type at the bottom.
- The page reads top-down: situation → complication → resolution.

### 1.3 Triage

**Permanent rules** (shared by 3 or more references):
1. The data is the loudest thing on the page. Everything else is quieter.
2. Titles state the message, backed by data. Subtitles define the metric.
3. One highlight colour. Everything else is neutral.
4. Label directly. Use a legend only when you have to.
5. A consistent spacing scale and a shared left edge.
6. Never rely on colour alone. Text must meet 4.5:1 contrast.
7. Nothing critical hidden behind a hover.
8. Consistent number formats and units, repeated where they're read.

**Useful in specific situations:**
- Annotations on outliers, such as Black Friday. Use them on explanatory pages, not monitoring pages.
- Small multiples, when comparing 3–8 segments over time.
- Fixed axis bounds, for percentages (0–100%) and before/after comparisons.
- Points on lines, only for sparse series (under 15 points).
- Conditional formatting, only in matrices used for lookup, and only one measure per matrix.

**Can't realistically be done in Power BI:**
- *Custom typefaces (SF Pro, Inter, Google Sans).* The Power BI service doesn't embed fonts. → Use **Segoe UI**, which is available everywhere Power BI runs.
- *Free-floating annotations attached to a data point.* → Use reference lines with labels, or a text box placed by the grid.
- *Animated transitions and scrubbing like Apple Stocks.* → Use tooltips and drill-through instead.
- *Text outlines and fine typographic control* (tracking, line height). → Rely on contrast and spacing instead.
- *Audio graphs (VoiceOver).* → Use alt text on every visual plus a sensible tab order.

---

## Part 2 · The design system

### 2.1 Identity

**Merch Store Analytics Review** is an independent case study, not a Google product. Every cover and dashboard carries the line *"Independent analysis of Google's public GA4 sample. Not affiliated with or endorsed by Google."* There is no Google logo and no use of Google's brand colours as a set.

The look is **Nordic**: cool grey-blue surfaces, a dark slate sidebar, a muted steel blue for the data and one aurora red for the thing to look at. The palette is adapted from the open-source Nord palette (Polar Night, Snow Storm, Frost and Aurora), with the darker steps adjusted so every text colour passes 4.5 : 1. The structure borrows the principles behind Material Design 3 (role-based colour, a type scale, an 8-point grid, accessible contrast). It should feel calm and corporate, and look polished because the information is well organised, not because it is decorated.

### 2.2 Design tokens

All colours and fonts live in one file, [`design/tokens.json`](../design/tokens.json), with semantic names. The Python chart style (`python/marketing_analytics/style.py`), the R chart style (`r/R/style.R`) and the Power BI theme (generated by `dashboard/build_pbip.py`) read it directly; the report, review report and deck use the same values in their CSS. Change a token, rebuild, and every output follows.

| Token | Value | Contrast on white | Use for | Never use for |
|---|---|---|---|---|
| `background.primary` | `#FFFFFF` | n/a | Cards, report pages, slides | |
| `background.secondary` | `#ECEFF4` | n/a | Dashboard page, grouped sections | Inside charts |
| `background.selected` | `#E5E9F0` | n/a | Decision strip, finding panels | Data |
| `text.primary` | `#2E3440` | 12.5 : 1 | Headlines, KPI values, important labels | |
| `text.secondary` | `#4C566A` | 7.4 : 1 | Subtitles, axis labels, captions | Headlines |
| `text.muted` | `#5C667A` | 5.8 : 1 | Source lines, footnotes | Anything important |
| `border.subtle` | `#D8DEE9` | n/a | Card borders, gridlines, table rules | Data |
| `data.primary` | `#5E81AC` | 4.0 : 1 | The main series | Small text |
| `data.primary.strong` | `#3B5B85` | 6.9 : 1 | Blue text, the darkest heatmap step | Large fills |
| `data.secondary` | `#88C0D0` | n/a | Second series of the same measure | Text |
| `data.comparison` | `#CED6E2` | n/a | Comparison, "everything else", as reported | Anything the reader must read |
| `data.highlight` / `.text` | `#BF616A` / `#A3434C` | 4.1 / 6.1 : 1 | The one thing to look at on a chart (January, Organic Search) | Several marks at once |
| `status.positive` / `.text` | `#5E8C46` / `#4A7336` | n/a / 5.5 : 1 | ▲ favourable change, with the arrow and words | Category colours |
| `status.negative` / `.text` | `#BF616A` / `#A3434C` | n/a / 6.1 : 1 | ▼ unfavourable change, data-quality warnings | "Important" |
| `status.warning` / `.text` | `#EBCB8B` / `#8A6A1E` | n/a / 5.1 : 1 | Caution, qualified results, external-dataset labels | Decoration |
| `sequential.low → high` | `#E5E9F0` → `#3B5B85` | n/a | Heatmaps and matrices (one hue) | Diverging data |
| `sidebar.*` | `#2E3440` panel, `#ECEFF4` / `#A9B3C6` text, `#3B4252` selected with `#88C0D0` text | 5.0 : 1 or more on the panel | Dashboard sidebar, report header band | Content |
| `kpi.accents` | `#5E81AC #BF616A #EBCB8B #A3BE8C #B48EAD` | n/a | The thin bar on top of each KPI card | Meaning: they only tell cards apart |
| `categorical` | `#5E81AC #D08770 #88C0D0 #B48EAD #A3BE8C #EBCB8B #81A1C1 #4C566A` | n/a | Only when a chart truly needs several categories | Cycling past eight |

**The colour rule:** steel blue for the data, grey for context, aurora red for the one thing to look at, and green and red arrows only for good and bad change. Never colour alone: every coloured mark also has a label, an arrow or a position that carries the meaning, so the red highlight and a red ▼ can't be confused. Red marks attention, not necessarily bad news; the title says which.

### 2.3 Typography

Segoe UI throughout (Roboto, then Arial as fallbacks). It's installed on every Windows machine and in the Power BI service, so the dashboard looks the same everywhere; Google Sans isn't freely licensed and Roboto isn't available to Power BI by default. The deck loads Roboto from Google Fonts for readers not on Windows.

| Role | PDF report | Power BI | Deck (1920×1080) |
|---|---|---|---|
| Cover title | 30 pt semibold | n/a | 80 px bold |
| Section heading | 18 pt semibold | 20 pt page title | 52 px bold |
| Main finding | 12 pt semibold in a finding panel | 11 pt line under the title | 28 px |
| KPI value | 24 pt regular, tabular figures | 26 pt regular | 64 px |
| Chart title | 11.5 pt semibold, states the finding | 12 pt semibold | 32 px |
| Body | 10.5 pt | n/a | 26 px |
| Chart labels | 9 pt | 9 pt | 22 px |
| Source notes | 8.5 pt | 8 pt | 20 px |

Sentence case everywhere. Numbers: `$338.3K`, `5,288 orders`, `1.47%`; one decimal on percentages unless the change is smaller than a point; `pts` for percentage-point differences, `%` for relative change, never mixed up.

### 2.4 Spacing and layout

8-point spacing: 8 inside components, 16 between related elements and as card padding, 24 between groups, 32 between sections, 48+ for page-level breaks. Every medium has its own grid:

- **Power BI:** 1440 × 900 canvas. A 224 px dark slate sidebar (product name, three dropdown filters on white, page buttons, independence note). One card per KPI, each with a thin accent bar on top. Content starts at x = 240 on 12 columns of 84 px with 16 px gutters. Bands: title 16–72, KPI card 84–188, primary story 204–500, supporting evidence 516–780, decision strip 796–864, source line 872–892.
- **PDF report:** A4, 16–18 mm margins, a single 178 mm column with two-up chart grids where charts are read together.
- **Deck:** 1920 × 1080, 128 px side margins, title block top-left, evidence left, reading right.

### 2.5 Chart grammar

| Question | Chart | Treatment |
|---|---|---|
| How has a metric changed? | Line or area | Thin gridlines on the value axis, no axis titles, annotate only what changes the reading |
| Which categories differ? | Horizontal bar, sorted | Direct labels on bar ends, no value axis, highlight one bar in red, rest grey |
| Where do people drop out? | Funnel plus a step-rate table | Counts on the funnel; rates stated with their denominator ("% of the previous step") |
| How do attribution models differ? | Heatmap | One hue, model names spelled out, darker = more credit |
| How uncertain is it? | Point with a 95% interval, or an interval column | Interval explained in the subtitle; sample size stated |
| How are values distributed? | Histogram or value bands | Median and mean both shown; skew visible |
| Do customers come back? | Cohort grid or repeat curve | Only cohorts that could be followed the whole window; counts alongside rates |
| What's bought together? | Ranked pair table | Minimum 30 shared orders; lift explained |
| How good is a forecast? | Actuals plus forecast band | History and forecast clearly separated |
| How reliable is the data? | As reported vs corrected table | Raw value, corrected value, treatment, range |

Never: 3D, gauges, shadows, gradients, decorative doughnuts, legends where a direct label works, truncated axes without a stated reason.

### 2.6 Uncertainty and evidence

- Every rate that's compared shows its denominator, and every comparison that could be noise shows a 95% interval (Wilson for single rates, normal approximation for differences, bootstrap for model shares).
- "No difference" is never claimed. The wording is *"No clear difference was detected; the intervals include zero."*
- Observed, estimated and modelled numbers are labelled as such. Model outputs (Markov shares, lifetime value, forecasts, media mix) say "estimated" or "modelled" in the subtitle.
- Missing or excluded data is noted where it affects the reading (for example "excludes 26 to 31 Jan, when order values weren't recorded").
- Association is not cause: "multi-product orders are worth more" is an observation; bundles are a test.

### 2.7 The decision pattern

Each major finding is written the same way, in every medium:

1. **Finding:** what the data shows, in one sentence.
2. **Evidence:** the numbers, the sample size and the interval.
3. **Interpretation:** the plausible explanations, and what the data can't tell us.
4. **Next action:** what to investigate, test or change.

In Power BI this is the decision strip at the bottom of every page; in the report each section ends with it; in the deck it's the right-hand column.

### 2.8 External datasets

The email A/B test (Hillstrom, 2008) and the marketing mix model (Robyn's simulated data) are not about the Google store. Wherever they appear they carry the label **Methods demonstration: external dataset**, with the source, population and period, and they never sit on the same page or slide as store findings without that label.

### 2.9 One family, three media

| Element | Report | Power BI | Deck |
|---|---|---|---|
| Colours, chart palette, number formats | Shared tokens | Shared tokens | Shared tokens |
| Metric names | Canonical ("conversion rate" = orders per session) | Same | Same |
| Uncertainty | Intervals in tables and captions | Interval columns and KPI context lines | Intervals on the chart, one line in the notes |
| Data-quality notes | Full section | Source line and page subtitles | One slide, decision-relevant |
| Recommendations | Evidence and limitations | Decision strip | Decision narrative |

The dark one-page overview report keeps its own "Night" theme (`dashboard/theme_dark.json`). It is an alternative view of the same model and measures, not the primary product.

### 2.10 Power BI pages

| Page | Purpose | Dominant visual | Supporting evidence |
|---|---|---|---|
| Overview | The business picture in 30 seconds | Daily revenue | Channel credit; the January story in three columns (sessions, conversion, revenue per day) |
| Acquisition & attribution | Where visits come from and who gets credit | Top-8 country bars and session-channel scorecard | Credit as reported vs corrected; seven-model heatmap; Markov intervals |
| Conversion & landing pages | Where the journey loses buyers | Funnel and device table with intervals | Landing pages with intervals; possible explanations panel |
| Customers & retention | Who buys and whether they return | Segment shares | Time to second purchase; cohort grid with eligible counts; segment actions |
| Orders & products | Order composition and product opportunities | Order value bands | Basket comparison; product and category concentration; frequent pairs |

The session-channel scorecard (each visit's own channel) and the order-credit charts (corrected attribution) use different definitions, and each title says which one it is.
