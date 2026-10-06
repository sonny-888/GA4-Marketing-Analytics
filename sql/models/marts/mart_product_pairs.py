"""Products bought in the same order, with support, confidence and lift.

The maths lives in python/marketing_analytics/eda.py (unit-tested); pairs need 30+ shared orders,
because lift is unstable for rare products.
"""

from marketing_analytics.eda import basket_pairs


def model(dbt, session):
    dbt.config(materialized="table")

    items = dbt.ref("fct_order_items").df()
    items = items[["order_id", "item_name"]].rename(columns={"item_name": "product"})
    return basket_pairs(items, min_orders=30)
