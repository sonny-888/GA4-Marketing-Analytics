# Marketing mix model with Meta's Robyn.
#
# GA4 has no ad spend, so this uses Robyn's built-in example data: 208 weeks (2015 to 2019) of
# SIMULATED spend on TV, outdoor, print, Facebook and search, a newsletter, and revenue.
# The point is the method (adstock, saturation, ROAS, budget reallocation), not the numbers.
#
# Run from the project root:  Rscript r/mmm.R
# Quick check with a small search:  MMM_ITERATIONS=200 MMM_TRIALS=1 Rscript r/mmm.R
# The trained model is cached in data/mmm/ (about 50 minutes to fit); set MMM_REFIT=1 to retrain.
# Charts: figures/mmm/. Findings: docs/mmm.md

source("r/R/style.R")
suppressPackageStartupMessages({
  library(Robyn)
  library(dplyr)
  library(tidyr)
})

out <- "figures/mmm"
iterations <- as.integer(Sys.getenv("MMM_ITERATIONS", "2000"))
trials <- as.integer(Sys.getenv("MMM_TRIALS", "5"))

# Robyn's optimiser (nevergrad) runs in Python: use the project's virtual environment.
# On Windows the base Python's DLL folders must be on PATH before R can load it; their location
# comes from the environment's own pyvenv.cfg, so nothing machine-specific is hard-coded.
venv <- normalizePath(".venv", mustWork = TRUE)
base_python <- sub("^home *= *", "", grep("^home", readLines(file.path(venv, "pyvenv.cfg")), value = TRUE))
Sys.setenv(PATH = paste(c(base_python, file.path(base_python, c("Library/bin", "DLLs")), Sys.getenv("PATH")),
                        collapse = .Platform$path.sep))
reticulate::use_virtualenv(venv, required = TRUE)

data("dt_simulated_weekly", package = "Robyn")
data("dt_prophet_holidays", package = "Robyn")
# Robyn uses spend columns for money and media columns (impressions, clicks) for modelling; results
# come back under the media names, so keep a label lookup for each.
spend_labels <- c(tv_S = "TV", ooh_S = "Outdoor", print_S = "Print", facebook_S = "Facebook", search_S = "Search")
media_labels <- c(tv_S = "TV", ooh_S = "Outdoor", print_S = "Print", facebook_I = "Facebook", search_clicks_P = "Search")

# ---- model setup ------------------------------------------------------------------------------------
input <- robyn_inputs(
  dt_input = dt_simulated_weekly,
  dt_holidays = dt_prophet_holidays,
  date_var = "DATE",
  dep_var = "revenue", dep_var_type = "revenue",
  prophet_vars = c("trend", "season", "holiday"), prophet_country = "DE",
  context_vars = c("competitor_sales_B", "events"), factor_vars = "events",
  paid_media_spends = names(spend_labels),
  paid_media_vars = names(media_labels),
  organic_vars = "newsletter",
  window_start = "2016-01-01", window_end = "2018-12-31",
  adstock = "geometric"
)

# Search ranges for each channel: alpha/gamma shape the saturation curve, theta is how much of
# this week's effect carries into next week. Ranges follow Robyn's guidance for weekly data:
# TV carries over longest, digital the least.
# Robyn names these after the media activity variables (e.g. facebook_I, search_clicks_P).
carryover <- list(tv_S = c(0.3, 0.8), ooh_S = c(0.1, 0.4), print_S = c(0.1, 0.4),
                  facebook_I = c(0, 0.3), search_clicks_P = c(0, 0.3), newsletter = c(0.1, 0.4))
hyper <- list()
for (v in input$all_media) {
  hyper[[paste0(v, "_alphas")]] <- c(0.5, 3)
  hyper[[paste0(v, "_gammas")]] <- c(0.3, 1)
  hyper[[paste0(v, "_thetas")]] <- carryover[[v]]
}
# Robyn matches hyperparameters by position: alphabetical order, train_size last.
hyper <- c(hyper[hyper_names("geometric", input$all_media)], list(train_size = c(0.5, 0.8)))
input <- robyn_inputs(InputCollect = input, hyperparameters = hyper)

# ---- fit (or load the cached fit) and pick a model --------------------------------------------------------
cache <- sprintf("data/mmm/robyn_%d_iter_%d_trials.rds", iterations, trials)
if (file.exists(cache) && Sys.getenv("MMM_REFIT") != "1") {
  outputs <- readRDS(cache)
} else {
  set.seed(2024)
  runs <- robyn_run(InputCollect = input, iterations = iterations, trials = trials,
                    ts_validation = TRUE, add_penalty_factor = FALSE)  # quiet = TRUE hits a Robyn 3.12 progress-bar bug
  outputs <- robyn_outputs(input, runs, pareto_fronts = "auto", clusters = trials > 1,
                           export = FALSE, plot_pareto = FALSE, quiet = TRUE)
  dir.create(dirname(cache), showWarnings = FALSE, recursive = TRUE)
  saveRDS(outputs, cache)
}

# Robyn returns many good models. Pick the one balancing fit error (NRMSE) and how plausible the
# split of credit is (DECOMP.RSSD), both scaled 0-1 across the candidates.
candidates <- outputs$resultHypParam |>
  filter(solID %in% outputs$allSolutions) |>
  mutate(score = sqrt(scales::rescale(nrmse)^2 + scales::rescale(decomp.rssd)^2))
best <- candidates |> slice_min(score, n = 1, with_ties = FALSE)
model_id <- best$solID

# ---- channel results ------------------------------------------------------------------------------------
decomp <- outputs$xDecompAgg |>
  filter(solID == model_id, rn %in% names(media_labels)) |>
  transmute(channel = media_labels[rn], spend = total_spend, revenue = xDecompAgg, roas = roi_total,
            spend_share, effect_share) |>
  arrange(desc(roas))

top_channel <- decomp$channel[1]
p_roas <- ggplot(decomp, aes(roas, reorder(channel, roas))) +
  geom_vline(xintercept = 1, colour = pal$border) +
  geom_col(aes(fill = highlight_fill(channel, top_channel)), width = 0.6) +
  geom_text(aes(label = sprintf("%.2f", roas)), hjust = -0.2, size = 3.4, colour = pal$ink_2, family = base_font) +
  annotate("text", x = 1, y = nrow(decomp) + 0.5, label = "break-even", hjust = -0.1, vjust = 0, size = 3,
           colour = pal$muted, family = base_font) +
  coord_cartesian(clip = "off") +
  scale_fill_identity() +
  scale_x_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(title = sprintf("%s returns the most per dollar spent", top_channel),
       subtitle = "Return on ad spend (revenue the model credits to each channel / its spend), 2016 to 2018",
       caption = "Simulated data from Meta's Robyn package. Model fitted with Robyn.") +
  theme_report(grid = "none") + theme(axis.text.x = element_blank())
save_chart(p_roas, file.path(out, "roas.png"), width = 8, height = 4)

biggest <- slice_max(decomp, spend_share, n = 1)
over <- filter(decomp, effect_share > spend_share) |> arrange(desc(effect_share))
share <- decomp |>
  select(channel, `Share of spend` = spend_share, `Share of effect` = effect_share) |>
  pivot_longer(-channel)
p_share <- ggplot(share, aes(value, reorder(channel, value), colour = name)) +
  geom_line(aes(group = channel), colour = pal$border, linewidth = 1.2) +
  geom_point(size = 3.4) +
  scale_colour_manual(values = c(`Share of spend` = pal$context, `Share of effect` = pal$primary)) +
  scale_x_continuous(labels = scales::percent_format(accuracy = 1)) +
  labs(title = sprintf("%s takes %s of the budget; %s outperform their share",
                       biggest$channel, scales::percent(biggest$spend_share, accuracy = 1),
                       paste(over$channel, collapse = " and ")),
       subtitle = "Share of paid media spend (grey) and share of revenue the model credits to paid media (blue)",
       caption = "Simulated data from Meta's Robyn package.") +
  theme_report(grid = "x") + theme(legend.position = "top", legend.justification = "left")
save_chart(p_share, file.path(out, "spend_vs_effect.png"), width = 9, height = 4)

# ---- response curves: what extra spend buys ---------------------------------------------------------------------
curves <- lapply(names(spend_labels), function(ch) {
  avg <- mean(dt_simulated_weekly[[ch]][dt_simulated_weekly$DATE >= "2016-01-01" & dt_simulated_weekly$DATE <= "2018-12-31"])
  grid <- seq(0, avg * 2.5, length.out = 25)
  # One weekly spend level per call. metric_value is the TOTAL over date_range, so ask about a
  # single week ("last_1") to get the weekly response at that weekly spend, carry-over included.
  response <- vapply(grid, function(v) robyn_response(
    InputCollect = input, OutputCollect = outputs, select_model = model_id,
    metric_name = ch, metric_value = v, date_range = "last_1", quiet = TRUE)$sim_mean_response, numeric(1))
  data.frame(channel = spend_labels[[ch]], spend = grid, response = response, current = avg)
}) |> bind_rows()
current_pts <- curves |> group_by(channel) |> slice_min(abs(spend - current), n = 1) |> ungroup()

# "Saturated": the steepest part of the curve is behind today's spend, and the curve now rises less
# than half as fast as it did there. (A curve still bending upward at today's spend isn't saturated.)
saturation <- curves |>
  group_by(channel) |>
  mutate(slope = (response - lag(response)) / (spend - lag(spend))) |>
  summarise(slope_now = slope[which.min(abs(spend - current[1]))],
            slope_max = max(slope, na.rm = TRUE),
            steepest_at = spend[which.max(slope)],
            current = current[1]) |>
  mutate(saturated = steepest_at < current & slope_now < 0.5 * slope_max)
saturated <- saturation$channel[saturation$saturated]
room <- saturation |> filter(!saturated) |> arrange(desc(slope_now)) |> slice_head(n = 2)

p_curves <- ggplot(curves, aes(spend, response)) +
  geom_line(colour = pal$primary, linewidth = 0.9) +
  geom_point(data = current_pts, colour = pal$ink, size = 2.6) +
  facet_wrap(~channel, scales = "free", nrow = 1) +
  scale_x_continuous(labels = fmt_usd, n.breaks = 3) +
  scale_y_continuous(labels = fmt_usd, n.breaks = 4) +
  labs(title = sprintf("%s %s saturated; %s still have room to grow",
                       if (length(saturated)) paste(saturated, collapse = " and ") else "No channel",
                       if (length(saturated) == 1) "is" else "are", paste(room$channel, collapse = " and ")),
       subtitle = "Weekly revenue response by weekly spend. Dark dot: average weekly spend 2016 to 2018",
       caption = "Simulated data from Meta's Robyn package. Response includes carry-over from previous weeks.") +
  theme_report(grid = "y") + theme(panel.spacing = unit(1.2, "lines"))
save_chart(p_curves, file.path(out, "response_curves.png"), width = 10.5, height = 3.8)

# ---- budget reallocation: same total spend, moved to where it works harder ----------------------------------
alloc <- robyn_allocator(InputCollect = input, OutputCollect = outputs, select_model = model_id,
                         scenario = "max_response", channel_constr_low = 0.7, channel_constr_up = 1.5,
                         export = FALSE, plots = FALSE, quiet = TRUE)
plan <- alloc$dt_optimOut |>
  transmute(channel = media_labels[channels], current = initSpendUnit, recommended = optmSpendUnit,
            current_response = initResponseUnit, recommended_response = optmResponseUnit) |>
  mutate(change = recommended / current - 1)
uplift <- sum(plan$recommended_response) / sum(plan$current_response) - 1

p_alloc <- ggplot(plan, aes(y = reorder(channel, change))) +
  geom_segment(aes(x = current, xend = recommended, yend = reorder(channel, change)), colour = pal$border, linewidth = 1.2) +
  geom_point(aes(x = current), colour = pal$context, size = 3.4) +
  geom_point(aes(x = recommended, colour = change > 0), size = 3.4) +
  geom_text(aes(x = recommended, label = scales::percent(change, accuracy = 1, style_positive = "plus"), colour = change > 0),
            vjust = -1.1, size = 3.2, family = base_font) +
  scale_colour_manual(values = c(`TRUE` = pal$primary, `FALSE` = pal$ink_2), guide = "none") +
  scale_x_continuous(labels = fmt_usd) +
  labs(title = sprintf("Moving the same budget between channels could add about %s revenue",
                       scales::percent(uplift, accuracy = 1)),
       subtitle = "Average weekly spend now (grey) and recommended (blue up, dark grey down). Each channel kept within 70% to 150% of today",
       caption = "Simulated data from Meta's Robyn package. Robyn budget allocator, maximum response at the same total spend.") +
  theme_report(grid = "x")
save_chart(p_alloc, file.path(out, "budget.png"), width = 8.5, height = 4)

# ---- model fit ---------------------------------------------------------------------------------------------------
fit <- outputs$xDecompVecCollect |> filter(solID == model_id) |> select(ds, actual = dep_var, predicted = depVarHat)
p_fit <- ggplot(fit, aes(as.Date(ds))) +
  geom_line(aes(y = actual), colour = pal$context, linewidth = 0.8) +
  geom_line(aes(y = predicted), colour = pal$primary, linewidth = 0.8) +
  scale_y_continuous(labels = fmt_usd) +
  scale_x_date(date_labels = "%Y") +
  labs(title = sprintf("The model tracks weekly revenue closely (R-squared %.2f on training weeks)", best$rsq_train),
       subtitle = "Actual weekly revenue (grey) and the model's fit (blue)",
       caption = "Simulated data from Meta's Robyn package.") +
  theme_report()
save_chart(p_fit, file.path(out, "fit.png"), width = 9, height = 3.8)

# ---- summary for the memo -------------------------------------------------------------------------------------------
cat(sprintf("Model %s | R2 train %.2f val %.2f test %.2f | NRMSE train %.3f test %.3f | DECOMP.RSSD %.3f\n",
            model_id, best$rsq_train, best$rsq_val, best$rsq_test, best$nrmse_train, best$nrmse_test, best$decomp.rssd))
print(decomp, digits = 3)
print(plan, digits = 3)
print(saturation, digits = 3)
cat(sprintf("Reallocation uplift at the same spend: %+.1f%%\n", uplift * 100))
