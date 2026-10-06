"""Print every headline number quoted in the report, dashboards and deck, straight from the warehouse.

This is the single source of truth for figures in the written material: if a number appears in
report/report.pdf, the README or the deck, it is printed here (charts are drawn from the same tables).

Run after `dbt build` so written claims can be checked against the data:
    python python/scripts/headline_facts.py
"""

import math
from pathlib import Path

import duckdb

from marketing_analytics.eda import rate_difference, sample_size_per_arm, wilson

WAREHOUSE = Path(__file__).resolve().parents[2] / "warehouse.duckdb"


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    q = lambda sql: con.sql(sql).fetchall()  # noqa: E731

    sessions, users = q("select count(*), count(distinct user_pseudo_id) from marts.fct_sessions")[0]
    orders, revenue, no_id_orders, no_id_rev = q("""
        select count(*), sum(purchase_revenue_usd),
               count(*) filter (where not has_transaction_id),
               sum(purchase_revenue_usd) filter (where not has_transaction_id)
        from marts.fct_orders""")[0]
    raw_events, raw_rev = q("""select count(*), sum(purchase_revenue_usd)
                               from staging.stg_ga4__events where event_name = 'purchase'""")[0]
    print("== Volume")
    print(f"sessions {sessions:,} | users {users:,} | orders {orders:,} | revenue ${revenue:,.0f}")
    print(f"conversion {orders / sessions:.2%} | AOV ${revenue / orders:,.2f}")
    print(f"raw purchase events {raw_events:,} (${raw_rev:,.0f}) -> duplicates removed {raw_events - orders:,} "
          f"(${raw_rev - revenue:,.0f}, {(raw_rev - revenue) / revenue:.1%} overstatement)")
    print(f"orders recovered without transaction_id: {no_id_orders:,} (${no_id_rev:,.0f})")

    print("\n== Months")
    for m, s, o, r in q("""
        select d.month_label, count(*), sum(s.orders), sum(s.revenue_usd)
        from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
        group by d.month_label, d.month_sort order by d.month_sort"""):
        print(f"{m}: sessions {s:,} | orders {o:,} | revenue ${r:,.0f} ({r / revenue:.1%}) | cvr {o / s:.2%}")

    print("\n== Tracking health")
    bad_cart, bad_id = q("""select count(*) filter (where not is_cart_tracking_ok),
                                   count(*) filter (where not is_transaction_id_ok) from marts.dim_date""")[0]
    print(f"days with broken add_to_cart: {bad_cart} | days with purchases missing transaction_id: {bad_id}")
    bad_value = q("select string_agg(strftime(date, '%d %b'), ', ' order by date) from marts.dim_date where not is_revenue_tracking_ok")[0][0]
    print(f"days with missing purchase values: {bad_value}")
    for m, per_day in q("""
        select d.month_label, sum(s.revenue_usd) / count(distinct d.date)
        from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
        where d.is_revenue_tracking_ok group by d.month_label, d.month_sort order by d.month_sort"""):
        print(f"{m}: revenue per day on days with working revenue tracking ${per_day:,.0f}")

    print("\n== Funnel (days with working cart tracking only)")
    s, v, c, k, p = q("""
        select count(*), count_if(reached_view_item), count_if(reached_add_to_cart),
               count_if(reached_begin_checkout), count_if(reached_purchase)
        from marts.fct_sessions f join marts.dim_date d on d.date = f.session_date
        where d.is_cart_tracking_ok""")[0]
    print(f"session->view {v / s:.1%} | view->cart {c / v:.1%} | cart->checkout {k / c:.1%} | "
          f"checkout->purchase {p / k:.1%} | sessions ending in purchase {p / s:.2%}")

    print("\n== Channels (session channel)")
    for ch, s, o, r in q("""select session_channel_group, count(*), sum(orders), sum(revenue_usd)
                            from marts.fct_sessions group by 1 order by 2 desc"""):
        print(f"{ch:18s} sessions {s:>7,} ({s / sessions:5.1%}) | orders {o:>5,} | cvr {o / s:6.2%} | ${r:,.0f}")

    print("\n== Attribution")
    self_ref = q("select count(*) from marts.fct_orders where session_channel_group = 'Internal Referral'")[0][0]
    print(f"orders last-click credited to own site: {self_ref:,} ({self_ref / orders:.1%})")
    for ch, lc, mk, lo, hi in q("""
        select m.channel, lc.conversions, m.conversions, m.share_ci_low, m.share_ci_high
        from marts.attribution_markov m
        left join marts.mart_attribution_comparison lc on lc.channel = m.channel and lc.model = 'last_click'
        order by m.share desc"""):
        lc = lc or 0
        uplift = f"{mk / lc - 1:+.0%}" if lc else "n/a"
        print(f"{ch:16s} last click {lc:7.0f} | markov {mk:7.0f} ({uplift}) | CI {lo:.1%} to {hi:.1%}")
    for ch, lo, hi in q("""select channel, min(conversion_share), max(conversion_share)
                           from marts.mart_attribution_comparison where channel in ('Organic Search','Referral','Direct')
                           group by 1 order by 1"""):
        print(f"{ch} share across 7 models: {lo:.1%} to {hi:.1%}")
    single = q("""select avg((touches_in_path = 1)::int) from
                  (select distinct order_id, touches_in_path from intermediate.int_attribution__touchpoints)""")[0][0]
    print(f"single-session orders: {single:.0%}")

    print("\n== Measurement reliability: as reported vs corrected")
    id_orders, id_rev = q("""select count(*), sum(purchase_revenue_usd) from marts.fct_orders where has_transaction_id""")[0]
    no_id_events, no_id_event_rev = q("""
        select count(*), sum(purchase_revenue_usd) from staging.stg_ga4__events
        where event_name = 'purchase' and coalesce(transaction_id, '') in ('', '(not set)')""")[0]
    print(f"orders: as reported {raw_events:,} | corrected {orders:,} | range {id_orders:,} (no-ID all duplicates) "
          f"to {id_orders + no_id_events:,} (each no-ID event an order) | purchases with an ID {id_orders / orders:.0%}")
    print(f"revenue: as reported ${raw_rev:,.0f} | corrected ${revenue:,.0f} | range ${id_rev:,.0f} "
          f"to ${id_rev + no_id_event_rev:,.0f}")
    for label, flag_filter in [("all days", "true"), ("days with working cart tracking", "d.is_cart_tracking_ok")]:
        v2, c2, k2 = q(f"""select count_if(reached_view_item), count_if(reached_add_to_cart), count_if(reached_begin_checkout)
                          from marts.fct_sessions f join marts.dim_date d on d.date = f.session_date where {flag_filter}""")[0]
        print(f"{label}: view->cart {c2 / v2:.1%} | cart->checkout {k2 / c2:.1%}")
    unknown = q("""select sum(credit) from marts.fct_attribution_credits
                   where model = 'last_click' and channel = 'Unknown'""")[0][0] or 0
    print(f"self-referred orders {self_ref:,}: {self_ref - unknown:,.0f} back to real channels, "
          f"{unknown:,.0f} Unknown ({unknown / orders:.1%} of orders)")
    for ch, reported, corrected in q("""
        with r as (select session_channel_group as channel, count(*) * 1.0 / sum(count(*)) over () as s
                   from marts.fct_orders group by 1),
             c as (select channel, sum(credit) / sum(sum(credit)) over () as s
                   from marts.fct_attribution_credits where model = 'last_click' group by 1)
        select coalesce(r.channel, c.channel), coalesce(r.s, 0), coalesce(c.s, 0)
        from r full join c on r.channel = c.channel order by 3 desc"""):
        print(f"  {ch:18s} last-click share as reported {reported:5.1%} | corrected {corrected:5.1%}")

    print("\n== Funnel by device (days with working cart tracking)")
    dev = {d: rest for d, *rest in q("""
        select f.device_category, count(*), count_if(reached_view_item), count_if(reached_add_to_cart),
               count_if(reached_begin_checkout), count_if(reached_purchase)
        from marts.fct_sessions f join marts.dim_date d on d.date = f.session_date
        where d.is_cart_tracking_ok group by 1""")}
    for i, step in enumerate(["session->view", "view->cart", "cart->checkout", "checkout->purchase"]):
        (nm, km), (nd, kd) = (dev["mobile"][i], dev["mobile"][i + 1]), (dev["desktop"][i], dev["desktop"][i + 1])
        diff, lo, hi = rate_difference(km, nm, kd, nd)
        print(f"{step:20s} desktop {kd / nd:.1%} | mobile {km / nm:.1%} | mobile-desktop {diff * 100:+.1f} pts "
              f"({lo * 100:+.1f} to {hi * 100:+.1f})")
    print(f"of 100 product viewers: {100 * c / v:.0f} add to cart, {100 * k / v:.0f} start checkout, {100 * p / v:.0f} buy")

    print("\n== Landing pages (1,000+ sessions)")
    pages = q("""
        select landing_page_group, count(*), count_if(reached_purchase) from marts.fct_sessions
        where landing_page_group not in ('Other pages', '(not recorded)') group by 1 order by 2 desc""")
    known = q("select count(*), count_if(reached_purchase) from marts.fct_sessions where landing_page is not null")[0]
    site = known[1] / known[0]
    weak = [(pg, n, k_) for pg, n, k_ in pages if wilson(k_, n)[1] < site and n / known[0] > 0.03]
    print(f"site purchase rate {site:.2%} | {len(pages)} pages cover {sum(n for _, n, _ in pages) / known[0]:.0%} of visits")
    print(f"{len(weak)} big weak entry pages: {sum(n for _, n, _ in weak) / known[0]:.0%} of visits, "
          f"{sum(k_ for *_, k_ in weak) / known[1]:.0%} of purchases")
    for pg, n, k_ in weak:
        lo, hi = wilson(k_, n)
        print(f"  {pg[:45]:45s} {n:>7,} sessions | {k_:>4,} with a purchase | {k_ / n:.2%} ({lo:.2%} to {hi:.2%})")

    print("\n== January vs December (days with recorded order values)")
    (d_days, d_s, d_o, d_r), (j_days, j_s, j_o, j_r) = q("""
        select count(distinct d.date), count(*), sum(s.orders), sum(s.revenue_usd)
        from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
        where d.is_revenue_tracking_ok and d.month_label in ('Dec 2020', 'Jan 2021')
        group by d.month_label order by d.month_label""")
    parts = {"sessions per day": (j_s / j_days) / (d_s / d_days), "conversion": (j_o / j_s) / (d_o / d_s),
             "order value": (j_r / j_o) / (d_r / d_o)}
    total = (j_r / j_days) / (d_r / d_days)
    print(f"revenue per day ${d_r / d_days:,.0f} -> ${j_r / j_days:,.0f} ({total - 1:+.0%})")
    for name, ratio in parts.items():
        print(f"  {name:18s} {ratio - 1:+.0%} | {math.log(ratio) / math.log(total):.0%} of the drop")

    print("\n== Customers")
    n_cust, repeaters, median_spend, back14 = q("""
        select count(*), count(*) filter (where buying_days >= 2), median(revenue_usd),
               avg((days_to_repeat <= 14)::int) filter (where buying_days >= 2) from marts.dim_customers""")[0]
    print(f"customers {n_cust:,} | bought on 2+ days {repeaters / n_cust:.1%} | median spend ${median_spend:,.0f} | "
          f"repeat buyers back within 14 days {back14:.0%}")
    for seg, n, share_c, share_r in q("""
        select rfm_segment, count(*), count(*) * 1.0 / sum(count(*)) over (),
               sum(revenue_usd) / sum(sum(revenue_usd)) over () from marts.dim_customers group by 1 order by 4 desc"""):
        print(f"  {seg:22s} {n:>5,} customers ({share_c:.0%}) | {share_r:.0%} of revenue")
    for month, *cells in q("""
        select strftime(cohort_month, '%b %Y'),
               count(*) filter (where first_order_date <= date '2021-01-24'),
               avg((buying_days >= 2 and days_to_repeat <= 7)::int) filter (where first_order_date <= date '2021-01-24'),
               count(*) filter (where first_order_date <= date '2021-01-17'),
               avg((buying_days >= 2 and days_to_repeat <= 14)::int) filter (where first_order_date <= date '2021-01-17'),
               count(*) filter (where first_order_date <= date '2021-01-01'),
               avg((buying_days >= 2 and days_to_repeat <= 30)::int) filter (where first_order_date <= date '2021-01-01')
        from marts.dim_customers group by cohort_month order by cohort_month"""):
        e7, r7, e14, r14, e30, r30 = cells
        fmt = lambda r, e: f"{r:.1%}" if e and e >= 100 else "too few"  # noqa: E731
        print(f"  {month}: within 7 days {fmt(r7, e7)} | 14 days {fmt(r14, e14)} | 30 days {fmt(r30, e30)} "
              f"({e30:,} customers followed 30 days)")

    print("\n== Orders and products (order values: days with recorded values)")
    med, mean, n_val = q(f"""select median(purchase_revenue_usd), avg(purchase_revenue_usd), count(*) from marts.fct_orders o
                            join marts.dim_date d on d.date = o.order_date where d.is_revenue_tracking_ok""")[0]
    top10 = q("""
        with v as (select o.purchase_revenue_usd as v, count(*) over () as n,
                          row_number() over (order by o.purchase_revenue_usd desc, o.order_id) as rn
                   from marts.fct_orders o join marts.dim_date d on d.date = o.order_date where d.is_revenue_tracking_ok)
        select sum(v) filter (where rn <= floor(n * 0.1)) / sum(v) from v""")[0][0]  # exactly the top 10% of orders
    print(f"orders with values {n_val:,} | median ${med:,.0f} | mean ${mean:,.0f} | top 10% of orders {top10:.0%} of revenue")
    for basket, n, m in q("""select basket_type, count(*), median(purchase_revenue_usd) from marts.fct_orders o
                             join marts.dim_date d on d.date = o.order_date where d.is_revenue_tracking_ok
                             and basket_type <> 'No item detail' group by 1 order by 1"""):
        print(f"  {basket:16s} {n:>5,} orders | median ${m:,.0f}")
    multi = q("""select avg((basket_type = 'Several products')::int) from marts.fct_orders
                 where basket_type <> 'No item detail'""")[0][0]
    n_products, half = q("""
        with p as (select item_name, sum(item_revenue_usd) r from marts.fct_order_items group by 1),
             c as (select r, sum(r) over (order by r desc) / sum(r) over () as cum from p)
        select (select count(*) from p), count(*) filter (where cum < 0.5) + 1 from c""")[0]
    apparel = q("""select sum(item_revenue_usd) filter (where item_category = 'Apparel') / sum(item_revenue_usd)
                   from marts.fct_order_items""")[0][0]
    pairs = q("select count(*) from marts.mart_product_pairs")[0][0]
    print(f"orders with several products {multi:.0%} | top {half} of {n_products} products make half of product revenue | "
          f"Apparel {apparel:.0%} | pairs bought together in 30+ orders: {pairs}")

    print("\n== Test plan (two arms, 95% confidence, 80% power, January daily volumes)")
    jan_days, jan_viewers, jan_checkouts = q("""
        select count(distinct d.date), count_if(reached_view_item), count_if(reached_begin_checkout)
        from marts.fct_sessions f join marts.dim_date d on d.date = f.session_date
        where d.is_cart_tracking_ok and d.month_label = 'Jan 2021'""")[0]
    for test, base, per_day in [("product page, view->cart", c / v, jan_viewers / jan_days),
                                ("checkout, checkout->purchase", p / k, jan_checkouts / jan_days)]:
        for lift in (0.05, 0.10):
            n = sample_size_per_arm(base, lift)
            print(f"  {test:30s} baseline {base:.1%} +{lift:.0%}: {n:,} per arm, {2 * n / per_day:.0f} days")
    for base in (0.057, 0.088):
        n = sample_size_per_arm(base, 0.30)
        print(f"  second-purchase offer, 30-day repeat {base:.1%} +30%: {n:,} per arm, "
              f"{2 * n / (n_cust / 92):.0f} days")

    print("\n== Weekdays (revenue per day)")
    for dname, rpd, cvr in q("""
        select d.day_name, sum(s.revenue_usd) / count(distinct s.session_date), sum(s.orders) * 1.0 / count(*)
        from marts.fct_sessions s join marts.dim_date d on d.date = s.session_date
        where d.is_revenue_tracking_ok
        group by d.day_name, d.day_of_week_num order by d.day_of_week_num"""):
        print(f"{dname}: ${rpd:,.0f}/day | cvr {cvr:.2%}")

    print("\n== Products")
    for name, rev in q("""select item_name, sum(item_revenue_usd) from marts.fct_order_items
                          group by 1 order by 2 desc limit 8"""):
        print(f"{name}: ${rev:,.0f}")
    peak_date, peak_rev = q("""select session_date, sum(revenue_usd) from marts.fct_sessions
                               group by 1 order by 2 desc limit 1""")[0]
    print(f"\npeak day {peak_date} ${peak_rev:,.0f}")


if __name__ == "__main__":
    main()
