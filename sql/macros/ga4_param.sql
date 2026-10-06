{#- Extract one value from GA4's repeated event_params key/value array. -#}
{% macro ga4_param(key, value_type='string_value') -%}
list_filter(event_params, lambda p: p.key = '{{ key }}')[1].value.{{ value_type }}
{%- endmacro %}


{#- Some GA4 params arrive as string on some events and int on others (e.g. session_engaged). -#}
{% macro ga4_param_any(key) -%}
coalesce(
    {{ ga4_param(key, 'string_value') }},
    cast({{ ga4_param(key, 'int_value') }} as varchar),
    cast({{ ga4_param(key, 'double_value') }} as varchar)
)
{%- endmacro %}
