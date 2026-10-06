-- Order fact table: one row per deduplicated purchase, with the channel of the converting session
-- and the shape of the basket (how many different products, which value band).

with baskets as (

    select order_id, count(distinct item_name) as distinct_products
    from {{ ref('fct_order_items') }}
    group by order_id

)

select
    o.order_id,
    o.has_transaction_id,
    o.dedup_method,
    o.events_for_transaction,
    o.order_date,
    o.order_ts,
    o.user_pseudo_id,
    o.session_key,
    o.purchase_revenue_usd,
    o.tax_usd,
    o.shipping_usd,
    o.total_item_quantity,
    o.unique_items,
    s.session_source,
    s.session_medium,
    s.session_campaign,
    s.session_channel_group,
    s.device_category,
    s.geo_country,
    s.is_new_user_session,
    coalesce(b.distinct_products, 0)                                     as distinct_products,
    case
        when b.distinct_products > 1 then 'Several products'
        when b.distinct_products = 1 then 'One product'
        else 'No item detail'
    end                                                                  as basket_type,
    case
        when o.purchase_revenue_usd < 10  then '< $10'
        when o.purchase_revenue_usd < 25  then '$10 to $25'
        when o.purchase_revenue_usd < 50  then '$25 to $50'
        when o.purchase_revenue_usd < 100 then '$50 to $100'
        when o.purchase_revenue_usd < 250 then '$100 to $250'
        else '$250 and over'
    end                                                                  as order_value_band,
    case
        when o.purchase_revenue_usd < 10  then 1
        when o.purchase_revenue_usd < 25  then 2
        when o.purchase_revenue_usd < 50  then 3
        when o.purchase_revenue_usd < 100 then 4
        when o.purchase_revenue_usd < 250 then 5
        else 6
    end                                                                  as order_value_band_sort
from {{ ref('int_ga4__purchases_deduped') }} o
left join {{ ref('int_ga4__sessions') }} s using (session_key)
left join baskets b using (order_id)
