"""Generate Snowflake SQL views from translated expressions."""

from jinja2 import Template
from typing import Dict, Any, List, Optional
import re


# View template for Snowflake
VIEW_TEMPLATE = Template("""
CREATE OR REPLACE VIEW {{ target_schema }}.{{ view_name }} AS
{% if comment -%}
-- {{ comment }}
{% endif -%}
{% if with_clause -%}
WITH {{ with_clause }}
{% endif -%}
{{ select_sql }};
""".strip())

# View with calculated columns template
VIEW_WITH_CALC_COLUMNS_TEMPLATE = Template("""
CREATE OR REPLACE VIEW {{ target_schema }}.{{ view_name }} AS
{% if comment -%}
-- {{ comment }}
{% endif -%}
WITH base AS (
{{ base_query | indent(2) }}
){% if joins %},
joined AS (
  SELECT base.*{% for join in join_columns %},
         {{ join }}{% endfor %}
  FROM base
  {{ join_clause | indent(2) }}
){% endif %}
SELECT {% if joins %}joined.*{% else %}base.*{% endif %}{% for col in calc_columns %},
       {{ col.expression }} AS {{ col.name }}{% endfor %}
FROM {% if joins %}joined{% else %}base{% endif %};
""".strip())


class SnowflakeViewGenerator:
    """Generate Snowflake views from translated SQL."""
    
    def __init__(self, target_schema: str = "SEMANTIC"):
        self.target_schema = target_schema
        self.generated_views = []
        
    def sanitize_view_name(self, name: str) -> str:
        """Sanitize table/view name for Snowflake."""
        # Remove special characters, replace spaces with underscores
        name = re.sub(r'[^\w\s]', '', name)
        name = name.replace(' ', '_')
        # Prefix with V_ to indicate it's a view
        return f"V_{name.upper()}"
    
    def sanitize_column_name(self, name: str) -> str:
        """Sanitize column name for Snowflake."""
        # Remove special characters except underscores
        name = re.sub(r'[^\w]', '_', name)
        return name.upper()
    
    def generate_simple_view(self, view_name: str, select_sql: str, 
                            comment: Optional[str] = None) -> str:
        """Generate a simple view."""
        sanitized_name = self.sanitize_view_name(view_name)
        
        return VIEW_TEMPLATE.render(
            target_schema=self.target_schema,
            view_name=sanitized_name,
            select_sql=select_sql,
            comment=comment
        )
    
    def generate_view_with_calc_columns(self, view_name: str, base_query: str,
                                       calc_columns: List[Dict[str, str]],
                                       join_clause: Optional[str] = None,
                                       join_columns: Optional[List[str]] = None,
                                       comment: Optional[str] = None) -> str:
        """Generate a view with calculated columns."""
        sanitized_name = self.sanitize_view_name(view_name)
        
        # Sanitize calculated column names
        for col in calc_columns:
            col['name'] = self.sanitize_column_name(col['name'])
        
        return VIEW_WITH_CALC_COLUMNS_TEMPLATE.render(
            target_schema=self.target_schema,
            view_name=sanitized_name,
            base_query=base_query,
            calc_columns=calc_columns,
            joins=bool(join_clause),
            join_clause=join_clause or "",
            join_columns=join_columns or [],
            comment=comment
        )
    
    def generate_view_from_table_info(self, table_info: Dict[str, Any],
                                     m_sql: Optional[str] = None,
                                     dax_translations: Optional[List[Dict]] = None,
                                     relationships: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Generate view from complete table information."""
        table_name = table_info['name']
        result = {
            'table_name': table_name,
            'view_name': self.sanitize_view_name(table_name),
            'sql': None,
            'metadata': {
                'has_m_expression': bool(table_info.get('partitions')),
                'has_calc_columns': bool(table_info.get('calc_columns')),
                'is_calc_table': bool(table_info.get('calc_table_expression')),
                'confidence': 'low',
                'manual_review_needed': False
            }
        }
        
        # If it's a calculated table, handle specially
        if table_info.get('calc_table_expression'):
            result['sql'] = f"""-- Calculated Table: {table_name}
-- This table is defined entirely by a DAX expression and requires manual translation
-- Original DAX:
-- {table_info['calc_table_expression']}

CREATE OR REPLACE VIEW {self.target_schema}.{self.sanitize_view_name(table_name)} AS
-- TODO: Implement calculated table logic
SELECT 1 AS placeholder;"""
            result['metadata']['manual_review_needed'] = True
            return result
        
        # Build base query from M expression or direct table reference
        base_query = m_sql if m_sql else f"SELECT * FROM {table_name}"
        
        # If there are calculated columns, we need to build a more complex view
        if dax_translations and len(dax_translations) > 0:
            # Check if any calculated columns reference other tables (RELATED)
            referenced_tables = set()
            join_columns = []
            
            for dax_info in dax_translations:
                if 'RELATED' in dax_info.get('metadata', {}).get('functions_used', []):
                    # Extract referenced table from the SQL
                    matches = re.findall(r'(\w+)\.(\w+)', dax_info['sql'])
                    for table, column in matches:
                        if table.lower() != table_name.lower():
                            referenced_tables.add(table)
                            join_columns.append(f"{table}.{column}")
            
            # Generate join clause if needed
            join_clause = None
            if referenced_tables and relationships:
                joins = []
                for ref_table in referenced_tables:
                    # Find relationship
                    for rel in relationships:
                        if (rel.get('fromTable', '').upper() == table_name.upper() and 
                            rel.get('toTable', '').upper() == ref_table.upper()):
                            joins.append(
                                f"LEFT JOIN {ref_table} ON base.{rel.get('fromColumn', 'ID')} = {ref_table}.{rel.get('toColumn', 'ID')}"
                            )
                            break
                        elif (rel.get('toTable', '').upper() == table_name.upper() and 
                              rel.get('fromTable', '').upper() == ref_table.upper()):
                            joins.append(
                                f"LEFT JOIN {ref_table} ON base.{rel.get('toColumn', 'ID')} = {ref_table}.{rel.get('fromColumn', 'ID')}"
                            )
                            break
                
                if joins:
                    join_clause = '\n'.join(joins)
            
            # Build calculated columns list
            calc_columns = []
            for dax_info in dax_translations:
                calc_columns.append({
                    'name': dax_info['column_name'],
                    'expression': dax_info['sql']
                })
            
            result['sql'] = self.generate_view_with_calc_columns(
                table_name, 
                base_query,
                calc_columns,
                join_clause,
                join_columns if join_clause else None,
                comment=f"View for table {table_name} with calculated columns"
            )
            
            # Update metadata
            result['metadata']['confidence'] = 'medium'
            if any('LOOKUPVALUE' in d.get('metadata', {}).get('functions_used', []) 
                   for d in dax_translations):
                result['metadata']['confidence'] = 'low'
                result['metadata']['manual_review_needed'] = True
        else:
            # Simple view without calculated columns
            result['sql'] = self.generate_simple_view(
                table_name,
                base_query,
                comment=f"View for table {table_name}"
            )
            result['metadata']['confidence'] = 'high' if m_sql else 'medium'
        
        return result
    
    def format_sql(self, sql: str) -> str:
        """Format SQL for readability."""
        # Basic formatting - in production, use sqlparse or similar
        sql = re.sub(r',\s*', ',\n  ', sql)
        sql = re.sub(r'\s+FROM\s+', '\nFROM ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+WHERE\s+', '\nWHERE ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+AND\s+', '\n  AND ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+OR\s+', '\n  OR ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+GROUP BY\s+', '\nGROUP BY ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+ORDER BY\s+', '\nORDER BY ', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\s+LIMIT\s+', '\nLIMIT ', sql, flags=re.IGNORECASE)
        
        return sql