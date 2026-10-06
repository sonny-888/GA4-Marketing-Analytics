# Forecast daily sessions and orders for the GA4 store, two weeks ahead.
#
# Only 92 days of history (with the holidays in the middle), so models are compared with rolling
# back-tests first: forecast two weeks ahead from five points in December and January, measure the
# error, and only then pick a model. The final forecast goes no further ahead than the back-tests did.
#
# Run from the project root:  Rscript r/forecast.R      Charts: figures/forecast/

source("r/R/style.R")
suppressPackageStartupMessages({
  library(dplyr)
  library(tsibble)
  library(fable)
  library(fabletools)
})

out <- "figures/forecast"
horizon <- 14

con <- warehouse()
daily <- DBI::dbGetQuery(con, "
  select s.session_date as date, count(*) as sessions, sum(s.orders) as orders,
         max(d.is_holiday_peak::int) as holiday
  from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
  group by 1 order by 1") |>
  mutate(date = as.Date(date)) |>
  as_tsibble(index = date)
DBI::dbDisconnect(con, shutdown = TRUE)

candidates <- function(data, y) {
  data |> model(
    `Same day last week` = SNAIVE(!!sym(y) ~ lag("week")),
    `ETS` = ETS(!!sym(y)),
    `ARIMA` = ARIMA(!!sym(y)),
    `ARIMA + holiday flag` = ARIMA(!!sym(y) ~ holiday),
    `Regression: trend, weekday, holiday` = TSLM(!!sym(y) ~ trend() + season("week") + holiday)
  )
}

# ---- rolling back-tests: 14-day forecasts from five starting points ---------------------------------------
folds <- daily |> stretch_tsibble(.init = 49, .step = 7) |> filter(.id <= 5)
backtest <- lapply(c("sessions", "orders"), function(y) {
  fc <- candidates(folds, y) |> forecast(new_data = new_data(folds, horizon) |> mutate(holiday = 0L))
  accuracy(fc, daily) |>
    group_by(.model) |>
    summarise(MAPE = mean(MAPE), MASE = mean(MASE), .groups = "drop") |>
    mutate(metric = y)
}) |> bind_rows()

winner <- backtest |> group_by(metric) |> slice_min(MASE, n = 1) |> ungroup()
err <- setNames(winner$MAPE / 100, winner$metric)
backtest <- backtest |> left_join(select(winner, metric, best = .model), by = "metric")

p_bt <- ggplot(backtest, aes(MAPE / 100, reorder(.model, -MAPE))) +
  geom_col(aes(fill = ifelse(.model == best, pal$accent, pal$context)), width = 0.6) +
  geom_text(aes(label = scales::percent(MAPE / 100, accuracy = 0.1)), hjust = -0.15, size = 3.2,
            colour = pal$ink_2, family = base_font) +
  scale_fill_identity() +
  facet_wrap(~ factor(metric, c("sessions", "orders"), c("Daily sessions", "Daily orders")), scales = "free_x") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.25))) +
  labs(title = sprintf("Sessions can be forecast two weeks out to within about %s; daily orders can't",
                       scales::percent(err[["sessions"]], accuracy = 1)),
       subtitle = "Average error of two-week forecasts from five starting points, Dec to Jan (MAPE, lower is better). Best model in red.",
       caption = source_note()) +
  theme_report(grid = "none") +
  theme(axis.text.x = element_blank(), panel.spacing = unit(2, "lines"))
save_chart(p_bt, file.path(out, "backtest.png"), width = 9.5, height = 4)

# ---- final forecast with the back-test winner -------------------------------------------------------
future <- new_data(daily, horizon) |> mutate(holiday = 0L)
forecast_one <- function(y) {
  best <- winner$.model[winner$metric == y]
  candidates(daily, y) |> select(all_of(best)) |> forecast(new_data = future) |>
    hilo(c(80, 95)) |> unpack_hilo(c(`80%`, `95%`)) |>
    as_tibble() |> transmute(date, mean = .mean, lo80 = `80%_lower`, hi80 = `80%_upper`,
                             lo95 = `95%_lower`, hi95 = `95%_upper`, model = best)
}

plot_forecast <- function(y, label, fmt) {
  fc <- forecast_one(y)
  hist <- daily |> filter(date > max(date) - 42)
  ggplot() +
    geom_ribbon(data = fc, aes(date, ymin = pmax(lo95, 0), ymax = hi95), fill = pal$primary, alpha = 0.12) +
    geom_ribbon(data = fc, aes(date, ymin = pmax(lo80, 0), ymax = hi80), fill = pal$primary, alpha = 0.22) +
    geom_line(data = hist, aes(date, .data[[y]]), colour = pal$ink_2, linewidth = 0.6) +
    geom_line(data = fc, aes(date, mean), colour = pal$primary, linewidth = 0.9) +
    geom_vline(xintercept = max(daily$date) + 0.5, colour = pal$border) +
    annotate("text", x = max(daily$date) + 1, y = Inf, label = "Forecast", hjust = 0, vjust = 1.5,
             size = 3, colour = pal$muted, family = base_font) +
    scale_y_continuous(labels = fmt, limits = c(0, NA)) +
    scale_x_date(date_labels = "%e %b", date_breaks = "2 weeks") +
    labs(title = label, subtitle = sprintf("Last six weeks (grey) and forecast (blue). Model: %s. Shaded: 80%% and 95%% ranges",
                                           fc$model[1])) +
    theme_report()
}

sessions_fc <- forecast_one("sessions")
p_fc <- plot_forecast("sessions", sprintf("Expect about %s sessions a day over the next two weeks",
                                          scales::comma(mean(sessions_fc$mean), accuracy = 100)), fmt_count) +
  labs(caption = source_note("Assumes no new holiday or campaign. Daily orders are too noisy to forecast from this history."))
save_chart(p_fc, file.path(out, "forecast.png"), width = 9, height = 4.4)

# ---- summary for the memo -----------------------------------------------------------------------------------
print(backtest |> arrange(metric, MASE), n = Inf)
for (y in c("sessions", "orders")) {
  fc <- forecast_one(y)
  cat(sprintf("%s next %d days: total %s (80%% range of daily values %s to %s), recent daily average %s\n", y, horizon,
              scales::comma(sum(fc$mean)), scales::comma(min(fc$lo80)), scales::comma(max(fc$hi80)),
              scales::comma(mean(tail(daily[[y]], 14)))))
}
