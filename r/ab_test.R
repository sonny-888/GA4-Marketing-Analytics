# A/B test analysis: Hillstrom email experiment (MineThatData, 2008).
# 64,000 customers randomly split three ways: men's email, women's email, no email.
# Outcomes over the next two weeks: visited the site, bought, amount spent.
#
# Run from the project root:  Rscript r/ab_test.R
# Writes charts and tables to figures/ab/. Findings: docs/experimentation.md

source("r/R/style.R")
source("r/R/abtest.R")
suppressPackageStartupMessages(library(dplyr))

out <- "figures/ab"

# ---- data (downloaded once, then checked against a known fingerprint) -------------------------
csv <- "data/raw/hillstrom/hillstrom.csv"
url <- "http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
expected_md5 <- "0af45f3c7ee495ed5654b398b1aab809"
if (!file.exists(csv)) {
  dir.create(dirname(csv), showWarnings = FALSE, recursive = TRUE)
  download.file(url, csv, mode = "wb", quiet = TRUE)  # the site has no valid HTTPS certificate
}
if (unname(tools::md5sum(csv)) != expected_md5) stop("hillstrom.csv doesn't match the expected file. Delete it and re-run.")

d <- read.csv(csv) |>
  mutate(
    arm = factor(segment, c("No E-Mail", "Mens E-Mail", "Womens E-Mail"), c("No email", "Men's email", "Women's email")),
    past_purchase = case_when(mens == 1 & womens == 1 ~ "Bought both",
                              mens == 1 ~ "Bought men's only",
                              TRUE ~ "Bought women's only")
  )
metrics <- c(visit = "Visited site", conversion = "Bought", spend = "Spend per customer")
emails <- c("Men's email", "Women's email")

# ---- 1. Is the split healthy? -----------------------------------------------------------------------
srm_p <- srm_p_value(table(d$arm))
if (srm_p < 0.001) stop("Sample ratio mismatch: the randomisation looks broken, don't trust the results.")

# ---- 2. Main results: each email vs no email, Holm-corrected across all six tests ------------------
main <- expand.grid(arm = emails, metric = names(metrics), stringsAsFactors = FALSE) |>
  rowwise() |>
  mutate(r = list(compare_arms(d[[metric]][d$arm == arm], d[[metric]][d$arm == "No email"]))) |>
  tidyr::unnest_wider(r) |>
  ungroup() |>
  mutate(p_holm = p.adjust(p_value, "holm"), metric_label = factor(metrics[metric], metrics))

# Men's vs women's email directly, on each metric (Holm-corrected as its own family)
head_to_head <- do.call(rbind, lapply(names(metrics), \(m) cbind(
  metric = m, compare_arms(d[[m]][d$arm == "Men's email"], d[[m]][d$arm == "Women's email"]))))
head_to_head$p_holm <- p.adjust(head_to_head$p_value, "holm")

p_main <- ggplot(main, aes(lift, forcats::fct_rev(arm))) +
  geom_vline(xintercept = 0, colour = pal$border) +
  geom_errorbar(aes(xmin = lift_low, xmax = lift_high), orientation = "y", width = 0, linewidth = 1.6, colour = pal$primary, alpha = 0.35) +
  geom_point(size = 3.2, colour = pal$primary) +
  geom_text(aes(label = scales::percent(lift, accuracy = 1, style_positive = "plus")), vjust = -1.2,
            size = 3.3, colour = pal$ink_2, family = base_font) +
  facet_wrap(~metric_label, nrow = 1) +
  scale_x_continuous(labels = scales::percent_format(accuracy = 1), expand = expansion(mult = c(0.05, 0.12))) +
  labs(title = "Both emails worked, and the men's email beat the women's on every measure",
       subtitle = "Relative lift vs no email, with 95% confidence interval. All six results hold after a Holm correction.",
       caption = "Source: Hillstrom email experiment (MineThatData), 64,000 customers randomly split three ways, two-week outcomes.") +
  theme_report(grid = "x") +
  theme(panel.spacing = unit(1.6, "lines"))
save_chart(p_main, file.path(out, "main_effects.png"), width = 9.5, height = 3.8)

# ---- 3. Who does each email work for? (exploratory, Holm-corrected within this family) -------------
by_segment <- expand.grid(arm = emails, past_purchase = sort(unique(d$past_purchase)), stringsAsFactors = FALSE) |>
  rowwise() |>
  mutate(r = list({
    s <- d[d$past_purchase == past_purchase, ]
    compare_arms(s$conversion[s$arm == arm], s$conversion[s$arm == "No email"])
  })) |>
  tidyr::unnest_wider(r) |>
  ungroup() |>
  mutate(p_holm = p.adjust(p_value, "holm"), significant = p_holm < 0.05)

p_seg <- ggplot(by_segment, aes(diff, forcats::fct_rev(past_purchase))) +
  geom_vline(xintercept = 0, colour = pal$border) +
  geom_errorbar(aes(xmin = diff_low, xmax = diff_high, colour = significant), orientation = "y", width = 0, linewidth = 1.6, alpha = 0.35) +
  geom_point(aes(colour = significant), size = 3.2) +
  geom_text(aes(label = ifelse(significant, scales::number(diff * 100, accuracy = 0.01, style_positive = "plus", suffix = " pts"),
                               "no clear effect"), colour = significant),
            vjust = -1.2, size = 3.2, family = base_font) +
  scale_colour_manual(values = c(`TRUE` = pal$primary, `FALSE` = pal$muted)) +
  facet_wrap(~arm) +
  scale_x_continuous(labels = function(x) sprintf("%.1f", x * 100)) +
  labs(title = "The women's email only moved past women's-wear buyers; the men's email moved everyone",
       subtitle = "Change in conversion vs no email, by what the customer bought before (percentage points, 95% CI)",
       caption = "Exploratory split, Holm-corrected across the six comparisons. Source: Hillstrom email experiment (MineThatData).") +
  theme_report(grid = "x") +
  theme(panel.spacing = unit(1.6, "lines"))
save_chart(p_seg, file.path(out, "segment_effects.png"), width = 9.5, height = 3.9)

# ---- 4. CUPED: does pre-test data make the test more precise? ----------------------------------------
pre <- model.matrix(~ recency + history + mens + womens + newbie + channel + zip_code, d)[, -1]
cuped_tbl <- data.frame(
  metric = unname(metrics),
  past_spend_only = sapply(names(metrics), function(m) variance_reduction(d[[m]], cuped(d[[m]], d$history))),
  all_pre_test = sapply(names(metrics), function(m) variance_reduction(d[[m]], cuped(d[[m]], pre)))
)

# ---- 5. Power: what could a test this size detect? ---------------------------------------------------
base_rate <- mean(d$conversion[d$arm == "No email"])
n_arm <- sum(d$arm == "No email")
mde_here <- min_detectable_lift(base_rate, n_arm)
power_curve <- data.frame(lift = seq(0.05, 0.6, by = 0.01)) |>
  mutate(n = sapply(lift, \(l) sample_size_per_arm(base_rate, l)))

p_power <- ggplot(power_curve, aes(lift, n)) +
  geom_line(colour = pal$primary, linewidth = 0.9) +
  annotate("point", x = mde_here, y = n_arm, colour = pal$ink, size = 3) +
  annotate("text", x = mde_here + 0.02, y = n_arm * 1.35, hjust = 0, size = 3.3, colour = pal$ink, family = base_font,
           label = sprintf("This test: %s per group,\nreliably detects lifts of %s or more", scales::comma(n_arm),
                           scales::percent(mde_here, accuracy = 1))) +
  scale_y_log10(labels = fmt_count, breaks = c(1e4, 3e4, 1e5, 3e5, 1e6)) +
  scale_x_continuous(labels = scales::percent_format(accuracy = 1)) +
  labs(title = sprintf("Spotting a 10%% lift in conversion would need about %s customers per group",
                       scales::comma(sample_size_per_arm(base_rate, 0.10), accuracy = 1000)),
       subtitle = sprintf("Customers needed per group (log scale) by the relative lift you want to detect, at a %s base conversion rate",
                          scales::percent(base_rate, accuracy = 0.01)),
       caption = "80% power, 5% significance, two-sided. Source: Hillstrom email experiment (MineThatData).") +
  theme_report(grid = "y")
save_chart(p_power, file.path(out, "power.png"), width = 9, height = 4.4)

# ---- 6. Results table -----------------------------------------------------------------------------------
fmt_metric <- function(x, metric) ifelse(metric == "spend", sprintf("$%.2f", x), sprintf("%.2f%%", x * 100))
results_tbl <- main |>
  transmute(Email = arm, Metric = metric_label,
            `No email` = fmt_metric(control, metric), Email_value = fmt_metric(treatment, metric),
            Change = ifelse(metric == "spend", sprintf("+$%.2f", diff), sprintf("+%.2f pts", diff * 100)),
            `Relative lift` = sprintf("+%.0f%% (%.0f%% to %.0f%%)", lift * 100, lift_low * 100, lift_high * 100),
            `p (Holm)` = format.pval(p_holm, digits = 2, eps = 1e-10)) |>
  arrange(Metric, Email) |>
  gt::gt(groupname_col = "Metric") |>
  gt::cols_label(Email_value = "With email") |>
  gt_report(title = "Email experiment results",
          subtitle = sprintf("Each email vs no email over two weeks. Sample split check p = %.2f (healthy).", srm_p),
          source = "Source: Hillstrom email experiment (MineThatData). Relative-lift intervals ignore uncertainty in the no-email rate.")
save_table(results_tbl, file.path(out, "results_table.png"), width = 580, height = 450)

# ---- summary for the memo ---------------------------------------------------------------------------
cat(sprintf("SRM p = %.3f\n", srm_p))
print(as.data.frame(main[, c("arm", "metric", "control", "treatment", "diff", "lift", "lift_low", "lift_high", "p_holm")]), digits = 3)
print(head_to_head[, c("metric", "diff", "diff_low", "diff_high", "p_holm")], digits = 3)
print(as.data.frame(by_segment[, c("arm", "past_purchase", "diff", "diff_low", "diff_high", "p_holm")]), digits = 3)
print(cuped_tbl, digits = 2)
cat(sprintf("Base conversion %.2f%%, %d per group, MDE %.0f%%, n for 10%% lift %s\n",
            base_rate * 100, n_arm, mde_here * 100, scales::comma(sample_size_per_arm(base_rate, 0.10))))
