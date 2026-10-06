"""Data-driven attribution: first-order Markov chain removal effects with bootstrap 95% CIs.

The maths lives in python/marketing_analytics/attribution.py (unit-tested); this dbt Python model
just feeds it the journeys from int_attribution__paths.
"""

from marketing_analytics.attribution import attribute


def model(dbt, session):
    dbt.config(materialized="table")

    paths = dbt.ref("int_attribution__paths").df()
    n_boot = int(dbt.config.get("markov_bootstrap_iterations") or 200)

    result = attribute(paths, n_boot=n_boot, seed=42)
    result.insert(0, "model", "markov")
    return result
