# Trend charts for the GA4 store: revenue by weekday, the daily revenue curve, the January slump
# and a channel table. Uses the shared style in r/R/style.R.
# Run from the project root:  Rscript r/trends.R      Charts: figures/trends/

source("r/R/style.R")
suppressPackageStartupMessages({
  library(dplyr)
  library(patchwork)
  library(ggrepel)
})

con <- warehouse()
on.exit(DBI::dbDisconnect(con, shutdown = TRUE))
out <- "figures/trends"

# 1. Ranked bar with one highlight and direct labels -------------------------------------
weekday <- DBI::dbGetQuery(con, "
  select d.day_name, d.day_of_week_num, sum(s.revenue_usd) / count(distinct s.session_date) as revenue_per_day
  from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
  where d.is_revenue_tracking_ok
  group by all")
weekday$day_name <- factor(weekday$day_name, levels = weekday$day_name[order(weekday$day_of_week_num)])

p1 <- ggplot(weekday, aes(revenue_per_day, forcats::fct_rev(day_name))) +
  geom_col(aes(fill = highlight_fill(day_name, "Sun")), width = 0.62) +
  geom_text(aes(label = fmt_usd(revenue_per_day)), hjust = -0.15, size = 3.4, colour = pal$ink_2,
            family = base_font) +
  scale_fill_identity() +
  scale_x_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(title = "Sundays earn less than half a Friday's revenue",
       subtitle = "Average revenue per day, by weekday",
       caption = source_note("Excludes 26 to 31 Jan, when order values were missing.")) +
  theme_report(grid = "none") +
  theme(axis.text.x = element_blank())
save_chart(p1, file.path(out, "weekday.png"), width = 7, height = 4.2)

# 2. Trend line with annotations instead of a legend -----------------------------------------
daily <- DBI::dbGetQuery(con, "
  select session_date as date, sum(revenue_usd) as revenue from marts.fct_sessions group by 1 order by 1")
daily$date <- as.Date(daily$date)
peak <- daily[which.max(daily$revenue), ]
events <- data.frame(date = as.Date(c("2020-11-27", "2020-12-25")), label = c("Black Friday", "Christmas"))

p2 <- ggplot(daily, aes(date, revenue)) +
  geom_vline(data = events, aes(xintercept = date), colour = pal$border, linewidth = 0.6) +
  geom_text(data = events, aes(x = date, y = Inf, label = label), vjust = 1.5, hjust = -0.08,
            size = 3, colour = pal$muted, family = base_font) +
  geom_line(colour = pal$primary, linewidth = 0.8) +
  geom_point(data = peak, colour = pal$ink, size = 2.6) +
  geom_text_repel(data = peak, aes(label = paste0("Cyber Monday: ", fmt_usd(revenue))),
                  nudge_x = 12, nudge_y = 400, size = 3.3, colour = pal$ink, family = base_font,
                  segment.colour = pal$ink_2, segment.size = 0.3, min.segment.length = 0) +
  scale_y_continuous(labels = fmt_usd, expand = expansion(mult = c(0, 0.08))) +
  scale_x_date(date_labels = "%b %Y", date_breaks = "1 month") +
  labs(title = "Revenue peaked on Cyber Monday and stayed high until mid-December",
       subtitle = "Daily revenue (USD)", caption = source_note("Order values missing 26 to 31 Jan, so the last days read low.")) +
  theme_report()
save_chart(p2, file.path(out, "daily_revenue.png"), width = 9, height = 4.5)

# 3. Two related charts side by side (never a dual axis) ---------------------------------------
monthly <- DBI::dbGetQuery(con, "
  select d.month_label, d.month_sort, count(*) as sessions, sum(s.orders) * 1.0 / count(*) as cvr
  from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date group by all order by d.month_sort")
monthly$month_label <- factor(monthly$month_label, levels = monthly$month_label)
monthly$fill <- highlight_fill(monthly$month_label, "Jan 2021", pal$context)

p3a <- ggplot(monthly, aes(month_label, sessions, fill = fill)) +
  geom_col(width = 0.6) +
  geom_text(aes(label = fmt_count(sessions)), vjust = -0.6, size = 3.4, colour = pal$ink_2, family = base_font) +
  scale_fill_identity() + scale_y_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(title = "Traffic dipped 11% in January...", subtitle = "Sessions by month") +
  theme_report(grid = "none") + theme(axis.text.y = element_blank())
p3b <- ggplot(monthly, aes(month_label, cvr, fill = fill)) +
  geom_col(width = 0.6) +
  geom_text(aes(label = fmt_pct(2)(cvr)), vjust = -0.6, size = 3.4, colour = pal$ink_2, family = base_font) +
  scale_fill_identity() + scale_y_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(title = "...but conversion fell by almost half", subtitle = "Orders per session, by month") +
  theme_report(grid = "none") + theme(axis.text.y = element_blank())
p3 <- (p3a | p3b) + plot_annotation(caption = source_note(), theme = theme_report())
save_chart(p3, file.path(out, "january.png"), width = 9, height = 4.2)

# 4. Table with one colour-scaled column --------------------------------------------------------
channels <- DBI::dbGetQuery(con, "
  select session_channel_group as channel, count(*) as sessions, sum(orders) as orders,
         sum(orders) * 1.0 / count(*) as cvr, sum(revenue_usd) as revenue
  from marts.fct_sessions
  where session_channel_group not in ('Internal Referral', 'Unassigned')
  group by 1 order by sessions desc")

tbl <- gt::gt(channels) |>
  gt::cols_label(channel = "Channel", sessions = "Sessions", orders = "Orders", cvr = "Conversion",
                 revenue = "Revenue") |>
  gt::fmt_number(c(sessions, orders), decimals = 0) |>
  gt::fmt_percent(cvr, decimals = 2) |>
  gt::fmt_currency(revenue, decimals = 0) |>
  gt::data_color(columns = cvr, palette = pal$heat) |>
  gt_report(title = "Referral converts at 4.1%, about 17 times Direct",
          subtitle = "Session channel, full period. Email's high rate comes from only 197 sessions.")
save_table(tbl, file.path(out, "channel_table.png"), width = 600, height = 420)

cat("Saved to", out, "\n")
