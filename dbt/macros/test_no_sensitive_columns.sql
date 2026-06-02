{% test no_sensitive_columns(model, forbidden=[]) %}
{#-
  Fail the build if a sensitive / raw identifier column leaks into a Gold model.

  Restores heal-mesh's marquee `no_raw_phi_columns_in_gold` governance test,
  generalized so each profile declares its own forbidden columns in the model's
  schema YAML. The test inspects the materialized table's schema (not its rows)
  and returns one row per offending column; dbt fails the test when any row is
  returned.
-#}
select column_name
from information_schema.columns
where lower(table_name) = lower('{{ model.identifier }}')
  and lower(column_name) in (
    {%- for col in forbidden %}
    '{{ col | lower }}'{{ "," if not loop.last }}
    {%- endfor %}
  )
{% endtest %}
