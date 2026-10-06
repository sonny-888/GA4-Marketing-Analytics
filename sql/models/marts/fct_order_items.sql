-- One row per product line on a deduplicated order. Item revenue reconciles to order revenue (tested).

select
    d.order_id,
    d.order_date,
    d.session_key,
    i.item_id,
    i.item_name,
    i.item_brand,
    i.item_category,
    i.quantity,
    i.price_in_usd,
    i.item_revenue_in_usd                       as item_revenue_usd
from {{ ref('stg_ga4__event_items') }} i
join {{ ref('int_ga4__purchases_deduped') }} d using (event_key)
where i.event_name = 'purchase'
