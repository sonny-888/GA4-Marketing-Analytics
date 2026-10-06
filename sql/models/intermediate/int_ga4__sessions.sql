-- One row per session (user_pseudo_id + ga_session_id), with session-scoped attribution and funnel flags.
--
-- Session source/medium = the first non-null source/medium param seen in the session.
-- Sessions with no source param at all are treated as (direct)/(none), matching GA4's behaviour.

with events as (

    select * from {{ ref('stg_ga4__events') }}

),

sessions as (

    select
        session_key,
        any_value(user_pseudo_id)                                               as user_pseudo_id,
        any_value(ga_session_id)                                                as ga_session_id,
        max(ga_session_number)                                                  as ga_session_number,

        min(event_date)                                                         as session_date,
        min(event_ts)                                                           as session_start_ts,
        max(event_ts)                                                           as session_end_ts,

        arg_min(event_source, event_ts)   filter (where event_source is not null)   as first_source,
        arg_min(event_medium, event_ts)   filter (where event_medium is not null)   as first_medium,
        arg_min(event_campaign, event_ts) filter (where event_campaign is not null) as first_campaign,
        arg_min(page_location, event_ts)  filter (where event_name = 'page_view')   as landing_page,

        arg_min(device_category, event_ts)                                      as device_category,
        arg_min(device_os, event_ts)                                            as device_os,
        arg_min(browser, event_ts)                                              as browser,
        arg_min(geo_country, event_ts)                                          as geo_country,
        arg_min(geo_city, event_ts)                                             as geo_city,

        count(*)                                                                as events,
        count(*) filter (where event_name = 'page_view')                        as page_views,
        coalesce(sum(engagement_time_msec), 0) / 1000.0                         as engagement_time_sec,
        coalesce(bool_or(is_session_engaged), false)                            as is_engaged,

        bool_or(event_name = 'view_item')                                       as reached_view_item,
        bool_or(event_name = 'add_to_cart')                                     as reached_add_to_cart,
        bool_or(event_name = 'begin_checkout')                                  as reached_begin_checkout,
        bool_or(event_name = 'add_payment_info')                                as reached_add_payment_info,
        bool_or(event_name = 'purchase')                                        as reached_purchase

    from events
    group by session_key

)

select
    *,
    coalesce(first_source, '(direct)')  as session_source,
    coalesce(first_medium, '(none)')    as session_medium,
    coalesce(first_campaign, '(direct)') as session_campaign,
    {{ channel_group("coalesce(first_source, '(direct)')", "coalesce(first_medium, '(none)')", "first_campaign") }}
                                        as session_channel_group,
    ga_session_number = 1               as is_new_user_session,
    epoch(session_end_ts - session_start_ts) as session_duration_sec
from sessions
