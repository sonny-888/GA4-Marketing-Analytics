-- Daily tracking health checks, so reports can flag or exclude days where a tag was broken.
--
-- add_to_cart: on healthy days there are 1.1 to 2.3 add_to_cart events per begin_checkout.
-- Below 0.6 the tag was clearly not firing (people can't check out without a cart).
-- In this sample that's 22 days in November, mostly 1 to 24 Nov.
--
-- purchase value: from 26 Jan the purchase events stop carrying their real value (average order
-- falls from about $60 to $0) while order counts stay normal. Days whose average purchase value is
-- under half the typical day's are flagged so revenue figures can exclude them.

{% set min_cart_ratio = 0.6 %}
{% set min_value_ratio = 0.5 %}

with daily as (

    select
        event_date,
        count(*) filter (where event_name = 'add_to_cart')                             as add_to_cart_events,
        count(*) filter (where event_name = 'begin_checkout')                          as begin_checkout_events,
        count(*) filter (where event_name = 'purchase')                                as purchase_events,
        count(*) filter (where event_name = 'purchase' and transaction_id is null)     as purchases_without_id,
        avg(purchase_revenue_usd) filter (where event_name = 'purchase')               as avg_purchase_value_usd
    from {{ ref('stg_ga4__events') }}
    group by event_date

)

select
    event_date,
    add_to_cart_events,
    begin_checkout_events,
    purchase_events,
    purchases_without_id,
    avg_purchase_value_usd,
    add_to_cart_events >= {{ min_cart_ratio }} * begin_checkout_events     as is_cart_tracking_ok,
    purchases_without_id = 0                                                as is_transaction_id_ok,
    coalesce(avg_purchase_value_usd >= {{ min_value_ratio }} * median(avg_purchase_value_usd) over (), true)
                                                                            as is_revenue_tracking_ok
from daily
