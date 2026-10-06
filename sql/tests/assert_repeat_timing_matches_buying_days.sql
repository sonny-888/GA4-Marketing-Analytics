-- A customer has a second buying day exactly when they bought on 2+ days, and it comes after the first.
select user_pseudo_id, buying_days, days_to_repeat
from {{ ref('dim_customers') }}
where (buying_days >= 2) != (days_to_repeat is not null)
   or days_to_repeat <= 0
