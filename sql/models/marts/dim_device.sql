-- Device dimension shared by fct_sessions and fct_orders, so one slicer filters both.

select distinct
    device_category,
    case device_category
        when 'desktop' then 1
        when 'mobile'  then 2
        when 'tablet'  then 3
        else 4
    end as sort_order
from {{ ref('fct_sessions') }}
where device_category is not null
