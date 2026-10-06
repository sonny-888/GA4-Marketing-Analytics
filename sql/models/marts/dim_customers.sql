-- One row per customer: a browser (user_pseudo_id) that placed at least one order.
-- Adds RFM scores and a plain-English segment.
--
-- Frequency is counted as buying days, not orders: two orders on the same day are one shopping trip.
-- Only 7.5% of customers buy on more than one day in this 92-day sample, so frequency is
-- grouped as 1 / 2 / 3+ rather than scored 1-5 (a 1-5 score would be meaningless here).

with orders as (

    select * from {{ ref('fct_orders') }}

),

as_of as (

    -- "today" for recency = the day after the last order in the data
    select max(order_date) + 1 as as_of_date from orders

),

customers as (

    select
        user_pseudo_id,
        min(order_date)                         as first_order_date,
        max(order_date)                         as last_order_date,
        count(*)                                as orders,
        count(distinct order_date)              as buying_days,
        sum(purchase_revenue_usd)               as revenue_usd
    from orders
    group by user_pseudo_id

),

repeat_gap as (

    -- days from the first buying day to the next one (null = hasn't come back yet)
    select o.user_pseudo_id, min(date_diff('day', c.first_order_date, o.order_date)) as days_to_repeat
    from orders o
    join customers c using (user_pseudo_id)
    where o.order_date > c.first_order_date
    group by o.user_pseudo_id

),

scored as (

    select
        c.*,
        a.as_of_date,
        date_diff('day', c.last_order_date, a.as_of_date)                       as recency_days,
        date_diff('day', c.first_order_date, a.as_of_date)                      as tenure_days,
        case
            when date_diff('day', c.last_order_date, a.as_of_date) <= 14 then 5
            when date_diff('day', c.last_order_date, a.as_of_date) <= 30 then 4
            when date_diff('day', c.last_order_date, a.as_of_date) <= 45 then 3
            when date_diff('day', c.last_order_date, a.as_of_date) <= 60 then 2
            else 1
        end                                                                     as r_score,
        ntile(5) over (order by c.revenue_usd, c.user_pseudo_id)                as m_score
    from customers c
    cross join as_of a

)

select
    s.user_pseudo_id,
    s.first_order_date,
    s.last_order_date,
    date_trunc('month', s.first_order_date)::date                               as cohort_month,
    s.orders,
    s.buying_days,
    case when s.buying_days >= 3 then '3+' else s.buying_days::varchar end      as frequency_band,
    s.revenue_usd,
    s.revenue_usd / s.orders                                                    as avg_order_value_usd,
    s.recency_days,
    s.tenure_days,
    g.days_to_repeat,
    case
        when g.days_to_repeat <= 7  then 'Within a week'
        when g.days_to_repeat <= 14 then '8 to 14 days'
        when g.days_to_repeat <= 30 then '15 to 30 days'
        when g.days_to_repeat > 30  then 'Over 30 days'
    end                                                                         as repeat_window,
    case
        when g.days_to_repeat <= 7  then 1
        when g.days_to_repeat <= 14 then 2
        when g.days_to_repeat <= 30 then 3
        when g.days_to_repeat > 30  then 4
    end                                                                         as repeat_window_sort,
    s.r_score,
    s.m_score,
    case
        when s.buying_days >= 2 and s.r_score >= 4 then 'Champions'
        when s.buying_days >= 2                    then 'Repeat, lapsing'
        when s.m_score = 5                         then 'Big one-off spenders'
        when s.r_score >= 4                        then 'New customers'
        when s.r_score <= 2 and s.m_score >= 3     then 'At risk'
        else 'Low-value one-offs'
    end                                                                         as rfm_segment,
    u.first_session_channel_group                                               as acquisition_channel,
    u.first_device_category                                                     as first_device,
    u.first_geo_country                                                         as country
from scored s
join {{ ref('dim_users') }} u using (user_pseudo_id)
left join repeat_gap g using (user_pseudo_id)
