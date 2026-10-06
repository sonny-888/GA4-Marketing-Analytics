-- One row per GA4 event, with the commonly used event_params flattened into columns.

with source as (

    select * from {{ source('ga4', 'events') }}

),

flattened as (

    select
        md5(concat_ws('|', user_pseudo_id, event_timestamp, event_name, to_json(event_params))) as event_key,

        strptime(event_date, '%Y%m%d')::date                          as event_date,  -- property timezone
        make_timestamp(event_timestamp)                               as event_ts,    -- UTC
        event_name,

        user_pseudo_id,
        {{ ga4_param('ga_session_id', 'int_value') }}                 as ga_session_id,
        {{ ga4_param('ga_session_number', 'int_value') }}             as ga_session_number,
        user_pseudo_id || '-' || ga_session_id                        as session_key,

        {{ ga4_param('page_location') }}                              as page_location,
        {{ ga4_param('page_title') }}                                 as page_title,
        {{ ga4_param('page_referrer') }}                              as page_referrer,
        {{ ga4_param_any('session_engaged') }} = '1'                  as is_session_engaged,
        {{ ga4_param('engagement_time_msec', 'int_value') }}          as engagement_time_msec,
        {{ ga4_param('entrances', 'int_value') }} = 1                 as is_entrance,
        {{ ga4_param('search_term') }}                                as search_term,

        -- event-scoped attribution params (present on the event that started the visit)
        {{ ga4_param('source') }}                                     as event_source,
        {{ ga4_param('medium') }}                                     as event_medium,
        {{ ga4_param('campaign') }}                                   as event_campaign,
        {{ ga4_param('term') }}                                       as event_term,

        -- user-scoped first-touch acquisition
        traffic_source.source                                         as first_user_source,
        traffic_source.medium                                         as first_user_medium,
        traffic_source.name                                           as first_user_campaign,
        make_timestamp(user_first_touch_timestamp)                    as user_first_touch_ts,

        device.category                                               as device_category,
        device.operating_system                                       as device_os,
        device.web_info.browser                                       as browser,
        geo.continent                                                 as geo_continent,
        geo.country                                                   as geo_country,
        geo.region                                                    as geo_region,
        geo.city                                                      as geo_city,

        nullif(ecommerce.transaction_id, '(not set)')                 as transaction_id,
        ecommerce.purchase_revenue_in_usd                             as purchase_revenue_usd,
        ecommerce.tax_value_in_usd                                    as tax_usd,
        ecommerce.shipping_value_in_usd                               as shipping_usd,
        ecommerce.total_item_quantity                                 as total_item_quantity,
        ecommerce.unique_items                                        as unique_items,

        items

    from source

)

select * from flattened
