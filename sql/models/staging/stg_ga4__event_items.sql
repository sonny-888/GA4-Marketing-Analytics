-- One row per item on e-commerce events (view_item, add_to_cart, begin_checkout, purchase, ...).

with exploded as (

    select
        event_key,
        event_date,
        event_ts,
        event_name,
        user_pseudo_id,
        session_key,
        transaction_id,
        unnest(items) as item
    from {{ ref('stg_ga4__events') }}
    where len(items) > 0

)

select
    event_key,
    event_date,
    event_ts,
    event_name,
    user_pseudo_id,
    session_key,
    transaction_id,
    item.item_id,
    item.item_name,
    item.item_brand,
    item.item_variant,
    item.item_category,
    nullif(item.coupon, '(not set)')        as coupon,
    item.price_in_usd,
    item.quantity,
    item.item_revenue_in_usd,
    nullif(item.promotion_name, '')         as promotion_name,
    nullif(item.item_list_name, '(not set)') as item_list_name
from exploded
