-- All attribution models (rule-based and Markov) must distribute the same total conversions and revenue:
-- attribution re-allocates credit, it never creates or loses it.
with totals as (
    select model, sum(conversions) as conversions, sum(revenue_usd) as revenue_usd
    from {{ ref('mart_attribution_comparison') }}
    group by model
)
select *
from totals
where abs(conversions - (select max(conversions) from totals)) > 1e-6
   or abs(revenue_usd - (select max(revenue_usd) from totals)) > 1e-3
