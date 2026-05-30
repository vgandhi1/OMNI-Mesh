-- Singular dbt test: assert no raw PHI columns are ever exposed by the gold
-- layer. The query returns offending rows when violated; an empty result set
-- passes.
{% set forbidden_columns = ['mrn', 'first_name', 'last_name', 'email', 'dob'] %}

select column_name
from information_schema.columns
where lower(table_schema) like 'clinical_gold%'
  and lower(column_name) in ({{ "'" ~ forbidden_columns | join("','") ~ "'" }})
