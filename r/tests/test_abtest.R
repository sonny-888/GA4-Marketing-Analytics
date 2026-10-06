# Run from the project root:  Rscript -e "testthat::test_dir('r/tests')"
source(file.path("..", "R", "abtest.R"), chdir = TRUE)

test_that("SRM check flags a broken split and passes a fair one", {
  expect_gt(srm_p_value(c(10000, 10050)), 0.05)
  expect_lt(srm_p_value(c(10000, 11000)), 0.001)
})

test_that("compare_arms recovers a known difference in rates", {
  set.seed(1)
  ctrl <- rbinom(200000, 1, 0.10)
  treat <- rbinom(200000, 1, 0.12)
  r <- compare_arms(treat, ctrl)
  expect_equal(r$diff, 0.02, tolerance = 0.003)
  expect_true(r$diff_low < 0.02 && r$diff_high > 0.02)
  expect_equal(r$lift, 0.2, tolerance = 0.03)
})

test_that("CUPED keeps the treatment effect but shrinks the variance", {
  set.seed(2)
  n <- 50000
  pre <- rnorm(n, 100, 20)
  treat <- rep(0:1, length.out = n)
  y <- 0.8 * pre + 5 * treat + rnorm(n, 0, 10)
  adj <- cuped(y, pre)
  expect_equal(mean(adj[treat == 1]) - mean(adj[treat == 0]), 5, tolerance = 0.3)
  expect_gt(variance_reduction(y, adj), 0.6)
})

test_that("CUPED does nothing useful when pre-test data doesn't predict the outcome", {
  set.seed(3)
  y <- rnorm(20000)
  expect_lt(variance_reduction(y, cuped(y, rnorm(20000))), 0.01)
})

test_that("power helpers agree with each other", {
  n <- sample_size_per_arm(0.01, 0.2)
  expect_equal(min_detectable_lift(0.01, n), 0.2, tolerance = 0.005)
})
