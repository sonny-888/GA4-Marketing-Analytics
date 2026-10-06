-- The report describes two tracking faults by their dates: the add-to-cart tag broken on 22 days in November,
-- and order values missing from 26 to 31 January. If the detection rules change what they flag, this fails.
with flags as (
    select
        count(*) filter (where not is_cart_tracking_ok)                                    as cart_days,
        count(*) filter (where not is_cart_tracking_ok and month_label <> 'Nov 2020')       as cart_days_outside_nov,
        count(*) filter (where not is_revenue_tracking_ok)                                 as value_days,
        min(date) filter (where not is_revenue_tracking_ok)                                as value_first,
        max(date) filter (where not is_revenue_tracking_ok)                                as value_last
    from {{ ref('dim_date') }}
)
select *
from flags
where cart_days <> 22
   or cart_days_outside_nov <> 0
   or value_days <> 6
   or value_first <> date '2021-01-26'
   or value_last <> date '2021-01-31'
