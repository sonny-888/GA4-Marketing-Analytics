# Shared chart and table style for every R output in this project.
# Colours and fonts come from design/tokens.json, the same tokens as the Power BI theme,
# the Python charts, the report and the deck (docs/design_system.md).
#
# Rules this file enforces:
#   * title says the finding, subtitle says what's measured, caption says the source
#   * titles left-aligned to the whole plot, not the panel
#   * light gridlines on the value axis only, no axis titles unless needed
#   * blue carries the data; one aurora-red highlight marks the thing to look at, against grey context
#   * direct labels instead of legends wherever possible
#
# Usage (from the project root):  source("r/R/style.R")

suppressPackageStartupMessages({
  library(ggplot2)
  library(scales)
  library(systemfonts)
})

# ---- design tokens ------------------------------------------------------------
find_tokens <- function(dir = getwd()) {
  for (i in 1:4) {
    f <- file.path(dir, "design", "tokens.json")
    if (file.exists(f)) return(f)
    dir <- dirname(dir)
  }
  stop("Can't find design/tokens.json. Run from the project root.")
}
tokens <- jsonlite::fromJSON(find_tokens())
col <- tokens$color

pal <- list(
  primary   = col[["data.primary"]],         # the data, and the one thing to look at
  strong    = col[["data.primary.strong"]],
  secondary = col[["data.secondary"]],
  context   = col[["data.comparison"]],      # comparison / everything else
  accent    = col[["data.highlight"]],       # the one thing to look at, against grey context
  accent_tx = col[["data.highlight.text"]],
  positive  = col[["status.positive"]],
  negative  = col[["status.negative"]],
  ink       = col[["text.primary"]],
  ink_2     = col[["text.secondary"]],
  muted     = col[["text.muted"]],
  border    = col[["border.subtle"]],
  surface   = col[["background.primary"]],
  heat      = c(col[["sequential.low"]], col[["data.secondary"]], col[["sequential.high"]])
)

# Categorical order for charts that need several series. Never cycle it: fold extras into "Other".
pal_categorical <- col[["categorical"]]

base_font <- if (nrow(systemfonts::match_fonts(tokens$font$family)) > 0) tokens$font$family else ""

# ---- ggplot theme ---------------------------------------------------------------
theme_report <- function(base_size = 11, grid = "y") {
  t <- theme_minimal(base_size = base_size, base_family = base_font) +
    theme(
      plot.title.position   = "plot",
      plot.caption.position = "plot",
      plot.title    = element_text(face = "bold", size = rel(1.3), colour = pal$ink, margin = margin(b = 4)),
      plot.subtitle = element_text(size = rel(0.92), colour = pal$ink_2, margin = margin(b = 14)),
      plot.caption  = element_text(size = rel(0.72), colour = pal$muted, hjust = 0, margin = margin(t = 12)),
      axis.title    = element_blank(),
      axis.text     = element_text(size = rel(0.82), colour = pal$ink_2),
      axis.ticks    = element_blank(),
      panel.grid    = element_blank(),
      legend.position = "none",
      legend.title  = element_blank(),
      legend.text   = element_text(size = rel(0.8), colour = pal$ink_2),
      strip.text    = element_text(face = "bold", hjust = 0, colour = pal$ink, size = rel(0.9)),
      plot.background  = element_rect(fill = pal$surface, colour = NA),
      panel.background = element_rect(fill = pal$surface, colour = NA),
      plot.margin   = margin(20, 24, 16, 20)
    )
  gridline <- element_line(colour = pal$border, linewidth = 0.35)
  if (grid %in% c("y", "xy")) t <- t + theme(panel.grid.major.y = gridline)
  if (grid %in% c("x", "xy")) t <- t + theme(panel.grid.major.x = gridline)
  t
}

# Highlight one category in the accent colour, the rest in context grey.
highlight_fill <- function(x, which, others = pal$context) ifelse(x %in% which, pal$accent, others)

# ---- number formats (no false precision, units repeated) ----------------------
# One decimal on abbreviated numbers, trailing ".0" dropped: $3.9K, $2.5K, $5K, 360.1K
drop_zero <- function(x) sub("\\.0(?=[KMB]?$)", "", x, perl = TRUE)
fmt_usd   <- function(x) drop_zero(label_dollar(accuracy = 0.1, scale_cut = cut_short_scale())(x))
fmt_count <- function(x) drop_zero(label_number(accuracy = 0.1, scale_cut = cut_short_scale())(x))
fmt_pct   <- function(digits = 1) label_percent(accuracy = 10^-digits)      # 19.7%

source_note <- function(extra = NULL) {
  paste0("Source: GA4 public sample, Google Merchandise Store, 1 Nov 2020 to 31 Jan 2021.",
         if (!is.null(extra)) paste0(" ", extra) else "")
}

# ---- saving -----------------------------------------------------------------------
# ragg gives crisp anti-aliased text; 2x scale for retina screens and slides.
save_chart <- function(plot, file, width = 8, height = 4.5, dpi = 200) {
  dir.create(dirname(file), showWarnings = FALSE, recursive = TRUE)
  ggsave(file, plot, width = width, height = height, dpi = dpi, device = ragg::agg_png, bg = pal$surface)
  invisible(file)
}

# ---- gt table style -------------------------------------------------------------------
gt_report <- function(gt_tbl, title = NULL, subtitle = NULL, source = source_note()) {
  if (!requireNamespace("gt", quietly = TRUE)) stop("install.packages('gt')")
  out <- gt_tbl
  if (!is.null(title)) out <- gt::tab_header(out, title = gt::md(paste0("**", title, "**")), subtitle = subtitle)
  if (!is.null(source)) out <- gt::tab_source_note(out, source)
  gt::tab_options(
    out,
    table.font.names = c(base_font, "Segoe UI", "Arial", "sans-serif"),
    table.font.size = gt::px(13),
    table.font.color = pal$ink,
    table.border.top.style = "hidden",
    table.border.bottom.style = "hidden",
    heading.align = "left",
    heading.title.font.size = gt::px(17),
    heading.subtitle.font.size = gt::px(13),
    heading.border.bottom.style = "hidden",
    column_labels.font.weight = "bold",
    column_labels.font.size = gt::px(12),
    column_labels.text_transform = "none",
    column_labels.border.top.style = "hidden",
    column_labels.border.bottom.color = pal$ink,
    column_labels.border.bottom.width = gt::px(1.5),
    table_body.hlines.color = pal$border,
    table_body.border.bottom.color = pal$border,
    data_row.padding = gt::px(7),
    source_notes.font.size = gt::px(11),
    source_notes.padding = gt::px(10),
    table.margin.left = gt::px(0)
  ) |>
    gt::tab_style(gt::cell_text(color = pal$ink_2), gt::cells_title(groups = "subtitle")) |>
    gt::tab_style(gt::cell_text(color = pal$muted), gt::cells_source_notes()) |>
    gt::tab_style(gt::cell_text(color = pal$ink_2), gt::cells_column_labels())
}

# ---- data access ----------------------------------------------------------------------
# Read-only connection to the dbt warehouse (same DuckDB version as the Python side).
warehouse <- function(path = Sys.getenv("WAREHOUSE_PATH", "warehouse.duckdb")) {
  # Run scripts from the project root so the relative path resolves.
  if (!file.exists(path)) stop("Can't find ", path, ". Run from the project root or set WAREHOUSE_PATH.")
  DBI::dbConnect(duckdb::duckdb(shared_home = FALSE), path, read_only = TRUE)
}

# Save a gt table as HTML, plus a PNG rendered by headless Microsoft Edge when available.
# Fixed arguments only (no shell), so file paths can't inject commands.
save_table <- function(gt_tbl, file_png, width = 900, height = 600) {
  html <- sub("[.]png$", ".html", file_png)
  dir.create(dirname(html), showWarnings = FALSE, recursive = TRUE)
  gt::gtsave(gt_tbl, html)
  edge <- Filter(file.exists, c("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                                "C:/Program Files/Microsoft/Edge/Application/msedge.exe"))
  if (length(edge)) {
    system2(edge[1], c("--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                       sprintf("--window-size=%d,%d", width, height),
                       paste0("--screenshot=", normalizePath(file_png, mustWork = FALSE)),
                       paste0("file:///", normalizePath(html, winslash = "/"))),
            stdout = FALSE, stderr = FALSE)
  }
  invisible(file_png)
}
