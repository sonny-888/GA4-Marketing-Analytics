-- Rule-based attribution credit in long format: one row per (order, touchpoint, model).
-- Carries the order date so dashboards can filter attribution by date (the Markov model is
-- channel-level only and lives in attribution_markov).

with credits as (

    unpivot {{ ref('mart_attribution_touch_credits') }}
    on credit_first_click, credit_last_click, credit_last_non_direct_click,
       credit_linear, credit_time_decay, credit_position_based
    into name model value credit

)

select
    c.order_id,
    o.order_date,
    c.session_key,
    c.channel,
    c.touch_position,
    c.touches_in_path,
    replace(c.model, 'credit_', '')         as model,
    c.credit,
    c.credit * c.revenue_usd                as revenue_credit_usd
from credits c
join {{ ref('fct_orders') }} o using (order_id)
where c.credit > 0
