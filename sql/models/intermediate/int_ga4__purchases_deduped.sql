-- One row per real order.
--
-- GA4 sends duplicate purchase events (page reloads, retries), so we keep the first event per order.
-- How we recognise "the same order":
--   * transaction_id when it exists (4,451 orders)
--   * otherwise session + amount + basket contents. Purchases had no transaction_id on 11 days
--     (mostly early November), so dropping them would lose real sales. This match is slightly
--     aggressive: tested on orders that do have IDs it merges about 3.6% of genuine repeat orders,
--     so the no-ID count may be a little low.

with purchases as (

    select
        *,
        coalesce(
            transaction_id,
            'noid-' || md5(concat_ws('|',
                session_key,
                purchase_revenue_usd,
                to_json(list_sort(list_transform(items, lambda i: i.item_id || 'x' || i.quantity)))
            ))
        ) as order_key
    from {{ ref('stg_ga4__events') }}
    where event_name = 'purchase'

),

ranked as (

    select
        *,
        row_number() over (partition by order_key order by event_ts, event_key) as dup_rank,
        count(*) over (partition by order_key)                                   as events_for_order
    from purchases

)

select
    event_key,
    order_key                                         as order_id,
    transaction_id is not null                        as has_transaction_id,
    case when transaction_id is not null then 'transaction_id'
         else 'session_amount_basket' end             as dedup_method,
    events_for_order                                  as events_for_transaction,
    event_date                                        as order_date,
    event_ts                                          as order_ts,
    user_pseudo_id,
    session_key,
    purchase_revenue_usd,
    tax_usd,
    shipping_usd,
    total_item_quantity,
    unique_items,
    geo_country,
    device_category
from ranked
where dup_rank = 1
