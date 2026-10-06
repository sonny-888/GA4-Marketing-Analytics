import math

import pandas as pd
import pytest

from marketing_analytics.eda import basket_pairs, rate_difference, sample_size_per_arm, wilson


def test_wilson_matches_known_value():
    # 10 successes out of 100: textbook Wilson interval is about 5.5% to 17.4%
    lo, hi = wilson(10, 100)
    assert lo == pytest.approx(0.0552, abs=1e-3)
    assert hi == pytest.approx(0.1744, abs=1e-3)


def test_wilson_stays_inside_zero_and_one():
    lo, hi = wilson(0, 20)
    assert lo == pytest.approx(0, abs=1e-12) and 0 < hi < 0.2
    lo, hi = wilson(20, 20)
    assert 0.8 < lo < 1 and hi == pytest.approx(1)
    assert all(math.isnan(v) for v in wilson(0, 0))


def test_rate_difference_is_centred_and_symmetric():
    d, lo, hi = rate_difference(60, 100, 50, 100)
    assert d == pytest.approx(0.10)
    assert d - lo == pytest.approx(hi - d)
    assert lo < 0 < hi  # 60% vs 50% on 100 each is not a clear difference


def test_basket_pairs_support_confidence_lift():
    items = pd.DataFrame({
        "order_id": [1, 1, 2, 2, 3, 4, 4],
        "product": ["a", "b", "a", "b", "a", "c", "c"],  # order 4 has c twice: counted once
    })
    pairs = basket_pairs(items, min_orders=1)
    row = pairs.set_index(["product_a", "product_b"]).loc[("a", "b")]
    assert row.orders_together == 2
    assert row.support == pytest.approx(2 / 4)
    assert row.confidence_a_to_b == pytest.approx(2 / 3)  # a is in 3 orders
    assert row.confidence_b_to_a == pytest.approx(1.0)
    assert row.lift == pytest.approx(2 * 4 / (3 * 2))
    assert len(pairs) == 1


def test_basket_pairs_respects_minimum():
    items = pd.DataFrame({"order_id": [1, 1], "product": ["a", "b"]})
    assert basket_pairs(items, min_orders=2).empty


def test_sample_size_matches_textbook_value():
    # 10% -> 12% (20% relative lift), alpha 0.05, power 0.8: the standard answer is about 3,841 per arm
    assert sample_size_per_arm(0.10, 0.20) == pytest.approx(3841, abs=5)
    # smaller lifts need more data
    assert sample_size_per_arm(0.10, 0.10) > sample_size_per_arm(0.10, 0.20)
