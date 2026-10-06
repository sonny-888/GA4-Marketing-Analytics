-- Calendar dimension covering the data range. Mark as the date table in Power BI.
-- Carries daily tracking-health flags so reports can exclude days with broken tags.

with bounds as (

    select min(session_date) as start_date, max(session_date) as end_date
    from {{ ref('fct_sessions') }}

),

days as (

    select unnest(generate_series(start_date, end_date, interval 1 day))::date as date
    from bounds

)

select
    date,
    year(date)                                  as year,
    month(date)                                 as month_num,
    strftime(date, '%b %Y')                     as month_label,
    year(date) * 100 + month(date)              as month_sort,
    date_trunc('week', date)::date              as week_start,       -- ISO week, Monday start
    isodow(date)                                as day_of_week_num,  -- 1 = Monday
    strftime(date, '%a')                        as day_name,
    isodow(date) >= 6                           as is_weekend,
    case date
        when date '2020-11-27' then 'Black Friday'
        when date '2020-11-30' then 'Cyber Monday'
        when date '2020-12-25' then 'Christmas Day'
        when date '2021-01-01' then 'New Year''s Day'
    end                                         as retail_event,
    date between date '2020-11-27' and date '2020-12-24' as is_holiday_peak,
    coalesce(t.is_cart_tracking_ok, true)          as is_cart_tracking_ok,
    coalesce(t.is_transaction_id_ok, true)         as is_transaction_id_ok,
    coalesce(t.is_revenue_tracking_ok, true)       as is_revenue_tracking_ok
from days
left join {{ ref('int_ga4__tracking_quality') }} t on t.event_date = days.date
