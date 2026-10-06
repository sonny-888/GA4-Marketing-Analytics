-- Every order must hand out exactly 1 conversion of credit under every rule-based model.
select
    order_id,
    sum(credit_first_click)            as first_click,
    sum(credit_last_click)             as last_click,
    sum(credit_last_non_direct_click)  as last_non_direct_click,
    sum(credit_linear)                 as linear,
    sum(credit_time_decay)             as time_decay,
    sum(credit_position_based)         as position_based
from {{ ref('mart_attribution_touch_credits') }}
group by order_id
having abs(first_click - 1) > 1e-9
    or abs(last_click - 1) > 1e-9
    or abs(last_non_direct_click - 1) > 1e-9
    or abs(linear - 1) > 1e-9
    or abs(time_decay - 1) > 1e-9
    or abs(position_based - 1) > 1e-9
