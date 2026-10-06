"""Customer value scores: BG/NBD repeat-purchase model fitted on all customers.

Expected 90-day value = expected repeat buying days x the customer's own average order value.
Holdout check (fit Nov-Dec, predict Jan): notebooks/03_customers.ipynb. Maths: python/marketing_analytics/customers.py.
"""

from marketing_analytics.customers import expected_purchases, fit, p_alive


def model(dbt, session):
    dbt.config(materialized="table")

    c = dbt.ref("dim_customers").df()
    x = c["buying_days"] - 1
    t_x = c["tenure_days"] - c["recency_days"]
    T = c["tenure_days"]

    params = fit(x, t_x, T)
    c["p_alive"] = p_alive(params, x, t_x, T)
    c["expected_repeat_days_90d"] = expected_purchases(params, 90, x, t_x, T)
    c["expected_value_90d_usd"] = c["expected_repeat_days_90d"] * c["avg_order_value_usd"]
    for name in ("r", "alpha", "a", "b"):
        c[f"bgnbd_{name}"] = getattr(params, name)

    return c[["user_pseudo_id", "p_alive", "expected_repeat_days_90d", "expected_value_90d_usd",
              "bgnbd_r", "bgnbd_alpha", "bgnbd_a", "bgnbd_b"]]
