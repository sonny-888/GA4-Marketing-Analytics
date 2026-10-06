"""Small statistics helpers for the exploratory analysis (notebooks/04_eda.ipynb).

- wilson: confidence interval for a rate, reliable for small samples and rates near 0
- rate_difference: difference between two rates with a normal-approximation interval
- basket_pairs: products bought together, with support, confidence and lift
- sample_size_per_arm: how many units each arm of an A/B test needs to detect a given lift
"""

from __future__ import annotations

from itertools import combinations
from math import ceil, sqrt

import pandas as pd
from scipy.stats import norm

Z95 = 1.959964


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for successes / n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def rate_difference(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float, float]:
    """(p1 - p2, low, high): difference in percentage points as a fraction, with a 95% interval."""
    p1, p2 = k1 / n1, k2 / n2
    se = sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p1 - p2
    return (d, d - z * se, d + z * se)


def sample_size_per_arm(baseline: float, relative_lift: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Units per arm for a two-sided two-proportion test to detect baseline -> baseline * (1 + relative_lift)."""
    p1, p2 = baseline, baseline * (1 + relative_lift)
    pooled = (p1 + p2) / 2
    z_a, z_b = norm.ppf(1 - alpha / 2), norm.ppf(power)
    n = (z_a * sqrt(2 * pooled * (1 - pooled)) + z_b * sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
    return ceil(n)


def basket_pairs(items: pd.DataFrame, min_orders: int = 30) -> pd.DataFrame:
    """Pairs of products that appear in the same order.

    items: one row per (order_id, product); duplicates are ignored.
    Returns one row per unordered pair seen in at least `min_orders` orders, with
    support (share of all orders with both), confidence in each direction and lift
    (how much more often they appear together than if they were independent).
    """
    baskets = items.drop_duplicates().groupby("order_id")["product"].apply(lambda s: sorted(set(s)))
    n_orders = len(baskets)
    product_orders = items.drop_duplicates().groupby("product")["order_id"].nunique()
    counts: dict[tuple[str, str], int] = {}
    for basket in baskets:
        for pair in combinations(basket, 2):
            counts[pair] = counts.get(pair, 0) + 1
    rows = [(a, b, n) for (a, b), n in counts.items() if n >= min_orders]
    out = pd.DataFrame(rows, columns=["product_a", "product_b", "orders_together"])
    if out.empty:
        return out
    n_a = out.product_a.map(product_orders)
    n_b = out.product_b.map(product_orders)
    out["support"] = out.orders_together / n_orders
    out["confidence_a_to_b"] = out.orders_together / n_a
    out["confidence_b_to_a"] = out.orders_together / n_b
    out["lift"] = out.orders_together * n_orders / (n_a * n_b)
    return out.sort_values("orders_together", ascending=False).reset_index(drop=True)
