-- Fractional credit per touchpoint under six rule-based attribution models.
-- For every order, each model's credits sum to exactly 1.

{% set half_life = var('time_decay_half_life_days') %}

with touches as (

    select
        *,
        -- position of the last touch that isn't Direct or Unknown (null if there is none)
        max(touch_position) filter (where channel not in ('Direct', 'Unknown'))
            over (partition by order_id)                                   as last_non_direct_position,
        pow(2, -days_before_conversion / {{ half_life }})                  as decay_weight
    from {{ ref('int_attribution__touchpoints') }}

)

select
    order_id,
    user_pseudo_id,
    order_ts,
    revenue_usd,
    session_key,
    session_start_ts,
    channel,
    raw_channel_group,
    touch_position,
    touches_in_path,
    days_before_conversion,

    (touch_position = 1)::double                                           as credit_first_click,
    (touch_position = touches_in_path)::double                             as credit_last_click,
    (touch_position = coalesce(last_non_direct_position, touches_in_path))::double
                                                                           as credit_last_non_direct_click,
    1.0 / touches_in_path                                                  as credit_linear,
    decay_weight / sum(decay_weight) over (partition by order_id)          as credit_time_decay,
    case
        when touches_in_path = 1 then 1.0
        when touches_in_path = 2 then 0.5
        when touch_position in (1, touches_in_path) then 0.4
        else 0.2 / (touches_in_path - 2)
    end                                                                    as credit_position_based

from touches
