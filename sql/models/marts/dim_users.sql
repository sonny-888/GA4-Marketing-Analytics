-- User dimension: acquisition, activity and value per user_pseudo_id (cookie-level user).

with first_touch as (

    select
        user_pseudo_id,
        min(user_first_touch_ts)                    as first_touch_ts,
        arg_min(first_user_source, event_ts)        as first_user_source,
        arg_min(first_user_medium, event_ts)        as first_user_medium,
        arg_min(first_user_campaign, event_ts)      as first_user_campaign
    from {{ ref('stg_ga4__events') }}
    group by user_pseudo_id

),

activity as (

    select
        user_pseudo_id,
        min(session_date)                           as first_seen_date,
        max(session_date)                           as last_seen_date,
        count(*)                                    as sessions,
        count(*) filter (where is_engaged)          as engaged_sessions,
        sum(page_views)                             as page_views,
        sum(orders)                                 as orders,
        sum(revenue_usd)                            as revenue_usd,
        arg_min(session_channel_group, session_start_ts) as first_session_channel_group,
        arg_min(device_category, session_start_ts)  as first_device_category,
        arg_min(geo_country, session_start_ts)      as first_geo_country
    from {{ ref('fct_sessions') }}
    group by user_pseudo_id

)

select
    a.user_pseudo_id,
    f.first_touch_ts,
    a.first_seen_date,
    a.last_seen_date,
    f.first_user_source,
    f.first_user_medium,
    f.first_user_campaign,
    {{ channel_group('f.first_user_source', 'f.first_user_medium', 'f.first_user_campaign') }}
                                                    as first_user_channel_group,
    a.first_session_channel_group,
    a.first_device_category,
    a.first_geo_country,
    a.sessions,
    a.engaged_sessions,
    a.page_views,
    a.orders,
    a.revenue_usd,
    a.orders > 0                                    as is_customer
from activity a
left join first_touch f using (user_pseudo_id)
