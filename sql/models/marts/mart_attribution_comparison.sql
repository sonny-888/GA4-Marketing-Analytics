-- All attribution models side by side: one row per (model, channel). Feeds the Power BI attribution page.

with rule_based as (

    select
        model,
        channel,
        conversions,
        revenue_usd,
        null::double as share_ci_low,
        null::double as share_ci_high
    from {{ ref('mart_attribution_rule_based') }}

),

markov as (

    select
        model,
        channel,
        conversions,
        revenue_usd,
        share_ci_low,
        share_ci_high
    from {{ ref('attribution_markov') }}

),

unioned as (

    select * from rule_based
    union all
    select * from markov

)

select
    model,
    case model
        when 'first_click'           then 'First click'
        when 'last_click'            then 'Last click'
        when 'last_non_direct_click' then 'Last non-direct click'
        when 'linear'                then 'Linear'
        when 'time_decay'            then 'Time decay'
        when 'position_based'        then 'Position-based (40/20/40)'
        when 'markov'                then 'Data-driven (Markov)'
    end                                                                     as model_label,
    channel,
    conversions,
    revenue_usd,
    conversions / sum(conversions) over (partition by model)                as conversion_share,
    share_ci_low,
    share_ci_high,
    -- how much this model moves the channel vs. the last-click baseline most platforms report
    conversions - max(conversions) filter (where model = 'last_click')
        over (partition by channel)                                         as conversions_vs_last_click
from unioned
