-- Aggregated customer journeys (channel sequences) for data-driven attribution.
--
--   converting journeys     : the touchpoint path of each order
--   non-converting journeys : each user's sessions after their last order (or all sessions if they never bought)
--
-- Consecutive repeats are kept (Organic > Organic > Direct is a different path from Organic > Direct).

with converting as (

    select
        order_id                                            as journey_id,
        list(channel order by touch_position)               as path,
        true                                                as converted,
        any_value(revenue_usd)                              as revenue_usd
    from {{ ref('int_attribution__touchpoints') }}
    group by order_id

),

last_order as (

    select user_pseudo_id, max(order_ts) as last_order_ts
    from {{ ref('fct_orders') }}
    group by user_pseudo_id

),

sessions_after_last_order as (

    select
        s.*,
        count(*) filter (where not s.is_self_referral) over (partition by s.user_pseudo_id) as real_touch_count
    from {{ ref('int_attribution__sessions') }} s
    left join last_order l using (user_pseudo_id)
    where l.last_order_ts is null or s.session_start_ts > l.last_order_ts

),

non_converting as (

    select
        'user-' || user_pseudo_id                           as journey_id,
        list(channel order by session_start_ts, session_key) as path,
        false                                               as converted,
        0.0                                                 as revenue_usd
    from sessions_after_last_order
    where not is_self_referral or real_touch_count = 0     -- same self-referral rule as converting journeys
    group by user_pseudo_id

),

journeys as (

    select * from converting
    union all
    select * from non_converting

)

select
    path,
    array_to_string(path, ' > ')                            as path_label,
    len(path)                                               as path_length,
    converted,
    count(*)                                                as journeys,
    sum(revenue_usd)                                        as revenue_usd
from journeys
group by all
