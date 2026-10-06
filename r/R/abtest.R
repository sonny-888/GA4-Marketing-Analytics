# Small, tested building blocks for analysing A/B tests. Base R only.
# Unit tests: r/tests/test_abtest.R

# Sample ratio mismatch: did the randomisation produce the group sizes it was meant to?
# A tiny p-value means the split is broken and the test results can't be trusted.
srm_p_value <- function(n, expected = rep(1 / length(n), length(n))) {
  stats::chisq.test(n, p = expected)$p.value
}

# Treatment minus control for one metric. For 0/1 metrics (visit, conversion) this is the
# difference in rates. Welch's t-test, so unequal variances are fine.
compare_arms <- function(y_treat, y_ctrl) {
  tt <- stats::t.test(y_treat, y_ctrl)
  base <- mean(y_ctrl)
  data.frame(
    control = base,
    treatment = mean(y_treat),
    diff = mean(y_treat) - base,
    diff_low = tt$conf.int[1],
    diff_high = tt$conf.int[2],
    lift = (mean(y_treat) - base) / base,       # relative lift; its interval below ignores
    lift_low = tt$conf.int[1] / base,           # uncertainty in the control mean, which is
    lift_high = tt$conf.int[2] / base,          # small next to the difference at these sizes
    p_value = tt$p.value
  )
}

# CUPED: remove the part of the outcome that pre-test data already predicts.
# X can hold one or several pre-test columns. Theta is estimated on all arms pooled, which is
# valid because assignment is random. Returns the adjusted outcome (same mean, lower variance
# when X predicts y). Variance reduction = R-squared of y on X.
cuped <- function(y, X) {
  X <- scale(as.matrix(X), center = TRUE, scale = FALSE)
  theta <- stats::lm.fit(cbind(1, X), y)$coefficients[-1]
  theta[is.na(theta)] <- 0
  y - drop(X %*% theta)
}

variance_reduction <- function(y, y_adjusted) 1 - stats::var(y_adjusted) / stats::var(y)

# Customers needed per arm to detect a relative lift in a conversion rate.
sample_size_per_arm <- function(base_rate, relative_lift, alpha = 0.05, power = 0.8) {
  ceiling(stats::power.prop.test(p1 = base_rate, p2 = base_rate * (1 + relative_lift),
                                 sig.level = alpha, power = power)$n)
}

# Smallest relative lift a test of n per arm can reliably detect.
min_detectable_lift <- function(base_rate, n_per_arm, alpha = 0.05, power = 0.8) {
  stats::power.prop.test(n = n_per_arm, p1 = base_rate, sig.level = alpha, power = power)$p2 / base_rate - 1
}
