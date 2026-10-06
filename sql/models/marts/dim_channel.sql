-- Channel dimension for reporting (from the channels seed).

select
    channel,
    channel_type,
    sort_order,
    description,
    channel_type = 'Paid'                               as is_paid,
    channel_type in ('Unattributable', 'Tracking artefact') as is_measurement_gap
from {{ ref('channels') }}
