-- Conversions and revenue credited to each channel under each rule-based model (long format).

with credits as (

    unpivot {{ ref('mart_attribution_touch_credits') }}
    on credit_first_click, credit_last_click, credit_last_non_direct_click,
       credit_linear, credit_time_decay, credit_position_based
    into name model value credit

)

select
    replace(model, 'credit_', '')           as model,
    channel,
    sum(credit)                             as conversions,
    sum(credit * revenue_usd)               as revenue_usd
from credits
group by all
