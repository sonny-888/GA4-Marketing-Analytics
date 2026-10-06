-- Session fact table: one row per session, with deduplicated order revenue attached.

with sessions as (

    select * from {{ ref('int_ga4__sessions') }}

),

orders as (

    select
        session_key,
        count(*)                                           as orders,
        count(*) filter (where has_transaction_id)          as orders_with_id,
        sum(purchase_revenue_usd)                           as revenue_usd
    from {{ ref('int_ga4__purchases_deduped') }}
    group by session_key

),

joined as (

select
    s.session_key,
    s.user_pseudo_id,
    s.ga_session_number,
    s.is_new_user_session,
    s.session_date,
    s.session_start_ts,
    s.session_duration_sec,
    s.session_source,
    s.session_medium,
    s.session_campaign,
    s.session_channel_group,
    s.landing_page,
    s.device_category,
    s.device_os,
    s.browser,
    s.geo_country,
    s.geo_city,
    s.events,
    s.page_views,
    s.engagement_time_sec,
    s.is_engaged,
    s.reached_view_item,
    s.reached_add_to_cart,
    s.reached_begin_checkout,
    s.reached_add_payment_info,
    s.reached_purchase,
    coalesce(o.orders, 0)          as orders,
    coalesce(o.orders_with_id, 0)  as orders_with_id,
    coalesce(o.revenue_usd, 0)     as revenue_usd
from sessions s
left join orders o using (session_key)

),

with_path as (

    -- landing page without domain, query string, trailing slash or case, so the store's
    -- three home-page addresses count as one page
    select
        *,
        case
            when landing_page is null then null
            else coalesce(nullif(lower(rtrim(regexp_replace(regexp_replace(landing_page, '^https?://[^/]+', ''),
                                                            '[?#].*$', ''), '/')), ''), '/ (home)')
        end as landing_page_path
    from joined

)

select
    *,
    -- pages with 1,000+ sessions keep their name; the long tail is grouped so rates aren't read off tiny samples
    case
        when landing_page_path is null then '(not recorded)'
        when count(*) over (partition by landing_page_path) >= 1000 then landing_page_path
        else 'Other pages'
    end as landing_page_group
from with_path
