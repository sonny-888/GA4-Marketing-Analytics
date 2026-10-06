{#-
  Simplified GA4 default channel grouping, applied at session level.
  The public sample is obfuscated: '<Other>' and '(data deleted)' values can't be classified,
  so they get their own bucket rather than being silently folded into another channel.
-#}
{% macro channel_group(source, medium, campaign) -%}
case
    when {{ source }} in ('(data deleted)', '<Other>') and {{ medium }} in ('(data deleted)', '<Other>')
        then 'Obfuscated'
    when {{ medium }} = '(data deleted)'
        then 'Obfuscated'
    when {{ source }} = '(direct)' and {{ medium }} in ('(none)', '(not set)')
        then 'Direct'
    when {{ medium }} = 'referral' and {{ source }} in (
        {%- for d in var('internal_domains') %}'{{ d }}'{{ ", " if not loop.last }}{% endfor -%}
    )
        then 'Internal Referral'
    when {{ medium }} in ('cpc', 'ppc', 'paid', 'paidsearch')
        then 'Paid Search'
    when {{ medium }} = 'organic'
        then 'Organic Search'
    when {{ medium }} in ('display', 'cpm', 'banner', 'interstitial')
        then 'Display'
    when {{ medium }} in ('email', 'e-mail', 'e_mail')
        then 'Email'
    when {{ medium }} ilike '%affiliate%'
        then 'Affiliates'
    when {{ medium }} in ('social', 'social-network', 'social-media', 'sm')
        then 'Organic Social'
    when {{ medium }} = 'referral'
        then 'Referral'
    when {{ medium }} = '<Other>' or {{ source }} = '<Other>'
        then 'Obfuscated'
    else 'Unassigned'
end
{%- endmacro %}
