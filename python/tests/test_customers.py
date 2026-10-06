import numpy as np
import pandas as pd
import pytest

from marketing_analytics.customers import BGNBD, expected_purchases, fit, p_alive, summarise


def simulate(n: int, p: BGNBD, horizon: float, future: float, seed: int = 7):
    """Simulate BG/NBD customers: returns (x, t_x, T) over the horizon and repeat purchases in the next `future` days."""
    rng = np.random.default_rng(seed)
    lam = rng.gamma(p.r, 1 / p.alpha, n)
    drop = rng.beta(p.a, p.b, n)
    T = rng.uniform(horizon / 3, horizon, n)
    x, t_x, later = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        t, alive = 0.0, True
        while alive:
            t += rng.exponential(1 / lam[i])
            if t > T[i] + future:
                break
            if t <= T[i]:
                x[i], t_x[i] = x[i] + 1, t
            else:
                later[i] += 1
            alive = rng.random() > drop[i]
    return x, t_x, T, later


def test_p_alive_is_one_without_repeats_and_higher_when_recent():
    p = BGNBD(r=0.5, alpha=10, a=1.2, b=3)
    assert p_alive(p, 0, 0, 60) == pytest.approx(1.0)
    recent, stale = p_alive(p, [2, 2], [55, 10], [60, 60])
    assert recent > stale


def test_expected_purchases_grow_with_horizon():
    p = BGNBD(r=0.5, alpha=10, a=1.5, b=3)
    short, long = expected_purchases(p, 30, 1, 20, 60), expected_purchases(p, 90, 1, 20, 60)
    assert 0 <= short < long


def test_fit_predicts_future_purchases_on_simulated_customers():
    truth = BGNBD(r=0.3, alpha=40, a=1.5, b=4)
    x, t_x, T, later = simulate(4000, truth, horizon=60, future=30)
    fitted = fit(x, t_x, T)
    predicted = expected_purchases(fitted, 30, x, t_x, T).sum()
    assert predicted == pytest.approx(later.sum(), rel=0.15)


def test_summarise_counts_buying_days_not_orders():
    orders = pd.DataFrame({
        "user_pseudo_id": ["a", "a", "a", "b"],
        "order_date": ["2020-11-01", "2020-11-01", "2020-11-11", "2020-11-05"],
    })
    s = summarise(orders, "2020-11-21")
    assert s.loc["a"].tolist() == [1, 10, 20]   # two orders on day 1 count once
    assert s.loc["b"].tolist() == [0, 0, 16]
