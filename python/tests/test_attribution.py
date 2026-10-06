import numpy as np
import pandas as pd
import pytest

from marketing_analytics.attribution import attribute, markov_attribution


def test_single_channel_gets_all_credit():
    res = markov_attribution([("Email",), ("Email",)], [True, False])
    assert res.conversion_probability == pytest.approx(0.5)
    assert res.removal_effects["Email"] == pytest.approx(1.0)
    assert res.shares == {"Email": pytest.approx(1.0)}


def test_symmetric_channels_split_evenly():
    paths = [("A", "B"), ("B", "A"), ("A",), ("B",)]
    res = markov_attribution(paths, [True, True, False, False])
    assert res.shares["A"] == pytest.approx(res.shares["B"])
    assert sum(res.shares.values()) == pytest.approx(1.0)


def test_channel_that_never_precedes_conversion_gets_no_credit():
    # "Display" only appears on paths that never convert
    paths = [("Search",), ("Display",), ("Display",)]
    res = markov_attribution(paths, [True, False, False])
    assert res.shares["Display"] == pytest.approx(0.0)
    assert res.shares["Search"] == pytest.approx(1.0)


def test_weights_equal_repeated_rows():
    paths = [("A", "B"), ("B",), ("A",)]
    conv = [True, False, True]
    weighted = markov_attribution(paths, conv, [3, 2, 1])
    repeated = markov_attribution([paths[0]] * 3 + [paths[1]] * 2 + [paths[2]], [True] * 3 + [False] * 2 + [True])
    for c in ("A", "B"):
        assert weighted.shares[c] == pytest.approx(repeated.shares[c])


def test_attribute_conserves_totals():
    df = pd.DataFrame({
        "path": [["A", "B"], ["B"], ["A"], ["B", "A"]],
        "converted": [True, False, True, True],
        "journeys": [10, 50, 5, 8],
        "revenue_usd": [1000.0, 0.0, 300.0, 700.0],
    })
    out = attribute(df, n_boot=20)
    assert out["conversions"].sum() == pytest.approx(23)
    assert out["revenue_usd"].sum() == pytest.approx(2000.0)
    assert np.all(out["share_ci_low"] <= out["share_ci_high"])


def test_attribute_does_not_depend_on_row_order():
    df = pd.DataFrame({
        "path": [["A", "B"], ["B"], ["A"], ["B", "A"], ["C", "A"], ["C"]],
        "converted": [True, False, True, True, True, False],
        "journeys": [10, 50, 5, 8, 4, 20],
        "revenue_usd": [1000.0, 0.0, 300.0, 700.0, 200.0, 0.0],
    })
    a = attribute(df, n_boot=30).set_index("channel").sort_index()
    b = attribute(df.sample(frac=1, random_state=7), n_boot=30).set_index("channel").sort_index()
    pd.testing.assert_frame_equal(a, b)
