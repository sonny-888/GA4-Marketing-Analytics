-- One row per (order, touchpoint session): the sessions in a user's journey leading up to each order.
--
-- A journey = the user's sessions within the lookback window before the order, starting after their
-- previous order (so repeat purchases don't double-count earlier touches). The converting session is
-- always included, even if a previous order happened earlier in that same session.

{% set lookback = var('attribution_lookback_days') %}

with sessions as (

    select * from {{ ref('int_attribution__sessions') }}

),

orders as (

    select
        order_id,
        user_pseudo_id,
        session_key                                             as converting_session_key,
        order_ts,
        purchase_revenue_usd                                    as revenue_usd,
        lag(order_ts) over (partition by user_pseudo_id order by order_ts, order_id) as previous_order_ts
    from {{ ref('fct_orders') }}

),

joined as (

    select
        o.order_id,
        o.user_pseudo_id,
        o.order_ts,
        o.revenue_usd,
        s.session_key,
        s.session_start_ts,
        s.channel,
        s.raw_channel_group,
        s.is_self_referral,
        s.session_key = o.converting_session_key                   as is_converting_session
    from orders o
    join sessions s
      on s.user_pseudo_id = o.user_pseudo_id
     and (
            s.session_key = o.converting_session_key
         or (
                s.session_start_ts <= o.order_ts
            and s.session_start_ts >= o.order_ts - interval {{ lookback }} day
            and (o.previous_order_ts is null or s.session_start_ts > o.previous_order_ts)
            )
         )

),

-- drop self-referral sessions unless they're the only touches in the journey
real_touches as (

    select * exclude (real_touch_count)
    from (
        select
            *,
            count(*) filter (where not is_self_referral) over (partition by order_id) as real_touch_count
        from joined
    )
    where not is_self_referral or real_touch_count = 0

)

select
    *,
    row_number() over (partition by order_id order by session_start_ts, session_key) as touch_position,
    count(*) over (partition by order_id)                                             as touches_in_path,
    greatest(epoch(order_ts - session_start_ts), 0) / 86400.0                          as days_before_conversion
from real_touches
