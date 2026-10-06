-- Funnel stage dimension: gives the Power BI funnel its stage names and order.

select stage_order, stage_name, ga4_event, description
from {{ ref('funnel_stages') }}
