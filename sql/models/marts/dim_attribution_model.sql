-- Attribution model dimension: drives the model slicer on the Power BI attribution page.

select
    model,
    model_label,
    sort_order,
    is_data_driven,
    description
from {{ ref('attribution_models') }}
