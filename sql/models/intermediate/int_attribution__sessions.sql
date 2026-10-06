-- Sessions prepared as attribution touchpoints.
--
-- Self-referrals (the store's own domain, e.g. returning from the payment step) are not real visits:
-- GA4's referral exclusion would have continued the original session instead of starting a new one.
-- So they're flagged here and dropped from journeys downstream, handing credit to the touches before them.
-- If a journey consists only of self-referrals (earlier touches fell outside the data window),
-- they're kept and labelled Unknown: the customer came back from the payment page, but where they
-- first came from isn't in the data.

select
    session_key,
    user_pseudo_id,
    session_start_ts,
    session_channel_group                                   as raw_channel_group,
    session_channel_group = 'Internal Referral'             as is_self_referral,
    case
        when session_channel_group = 'Internal Referral' then 'Unknown'
        else session_channel_group
    end                                                     as channel
from {{ ref('fct_sessions') }}
