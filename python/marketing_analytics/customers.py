"""Customer lifetime value with the BG/NBD model (Fader, Hardie & Lee, 2005).

Each customer is summarised by three numbers, all in days:
    x    repeat buying days (buying days minus the first one)
    t_x  days from first to last purchase
    T    days from first purchase to the end of the observation window

The model assumes each customer buys at their own steady rate while "alive" and may drop out after
any purchase. Fitting it gives four population parameters (r, alpha, a, b), from which we get:
    p_alive            chance the customer is still active
    expected_purchases expected repeat buying days in the next t days
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln, hyp2f1


@dataclass(frozen=True)
class BGNBD:
    r: float
    alpha: float
    a: float
    b: float


def summarise(orders: pd.DataFrame, end_date) -> pd.DataFrame:
    """Per-customer x, t_x, T from an orders table (user_pseudo_id, order_date) up to end_date (exclusive)."""
    end = pd.Timestamp(end_date)
    days = (orders.assign(order_date=pd.to_datetime(orders["order_date"]))
            .query("order_date < @end")
            .drop_duplicates(["user_pseudo_id", "order_date"]))
    g = days.groupby("user_pseudo_id")["order_date"].agg(["min", "max", "count"])
    return pd.DataFrame({
        "x": g["count"] - 1,
        "t_x": (g["max"] - g["min"]).dt.days,
        "T": (end - g["min"]).dt.days,
    })


def _log_likelihood(p: BGNBD, x, t_x, T) -> np.ndarray:
    a1 = gammaln(p.r + x) - gammaln(p.r) + p.r * np.log(p.alpha)
    a2 = gammaln(p.a + p.b) + gammaln(p.b + x) - gammaln(p.b) - gammaln(p.a + p.b + x)
    a3 = -(p.r + x) * np.log(p.alpha + T)
    with np.errstate(divide="ignore", invalid="ignore"):
        a4 = np.where(x > 0, np.log(p.a) - np.log(p.b + x - 1) - (p.r + x) * np.log(p.alpha + t_x), -np.inf)
    return a1 + a2 + np.logaddexp(a3, a4)


def fit(x, t_x, T) -> BGNBD:
    """Maximum-likelihood fit. Parameters are optimised on the log scale so they stay positive."""
    x, t_x, T = (np.asarray(v, dtype=float) for v in (x, t_x, T))

    def nll(log_params):
        return -_log_likelihood(BGNBD(*np.exp(log_params)), x, t_x, T).sum()

    res = minimize(nll, x0=np.log([0.5, 10.0, 1.0, 1.0]), method="L-BFGS-B")
    if not res.success:
        raise RuntimeError(f"BG/NBD fit did not converge: {res.message}")
    return BGNBD(*np.exp(res.x))


def p_alive(p: BGNBD, x, t_x, T) -> np.ndarray:
    x, t_x, T = (np.asarray(v, dtype=float) for v in (x, t_x, T))
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(x > 0, p.a / (p.b + x - 1) * ((p.alpha + T) / (p.alpha + t_x)) ** (p.r + x), 0.0)
    return 1.0 / (1.0 + ratio)


def expected_purchases(p: BGNBD, t: float, x, t_x, T) -> np.ndarray:
    """Expected repeat buying days in the next t days for each customer."""
    x, t_x, T = (np.asarray(v, dtype=float) for v in (x, t_x, T))
    if p.a <= 1:
        raise ValueError("Expected purchases need a > 1; the fitted model can't project forward.")
    head = (p.a + p.b + x - 1) / (p.a - 1)
    tail = 1 - ((p.alpha + T) / (p.alpha + T + t)) ** (p.r + x) * hyp2f1(
        p.r + x, p.b + x, p.a + p.b + x - 1, t / (p.alpha + T + t))
    return head * tail * p_alive(p, x, t_x, T)
