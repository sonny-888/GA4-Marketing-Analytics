-- Product-line revenue must reconcile to deduplicated order revenue within 0.5%.
with items as (select sum(item_revenue_usd) as revenue from {{ ref('fct_order_items') }}),
orders as (select sum(purchase_revenue_usd) as revenue from {{ ref('fct_orders') }})
select items.revenue as item_revenue, orders.revenue as order_revenue
from items, orders
where abs(items.revenue - orders.revenue) > 0.005 * orders.revenue
