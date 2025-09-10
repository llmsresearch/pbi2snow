"""Unified Power BI to Snowflake translator with all enhancements integrated."""

import json
import re
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TranslationMode(Enum):
    """Translation modes for different levels of automation."""

    BASIC = "basic"  # Original translator
    ENHANCED = "enhanced"  # All enhancements enabled
    AGGRESSIVE = "aggressive"  # Try to translate everything, even with lower confidence


@dataclass
class TranslationConfig:
    """Configuration for translation behavior."""

    mode: TranslationMode = TranslationMode.ENHANCED
    enable_unpivot: bool = True
    enable_union_all: bool = True
    enable_nested_joins: bool = True
    enable_text_functions: bool = True
    enable_lookupvalue_translation: bool = True
    enable_calculated_table_patterns: bool = True
    parse_m_expressions: bool = True
    optimize_where_conditions: bool = True
    clean_bracket_references: bool = True
    max_lookupvalue_for_joins: int = 3  # Use JOINs if more than this many LOOKUPVALUEs
    confidence_threshold: float = 0.5
    verbose: bool = False
    strict_mode: bool = False  # Fail on any error vs best effort


@dataclass
class TranslationResult:
    """Result of a translation operation."""

    success: bool
    sql: str
    confidence: int
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    enhanced_features_used: List[str] = field(default_factory=list)


class MToSQLTranslator:
    """Unified M to SQL translator with all enhancements."""

    def __init__(self, config: TranslationConfig = None):
        self.config = config or TranslationConfig()
        self.all_steps = {}
        self.logger = logging.getLogger(self.__class__.__name__)

        # Text function mappings
        self.text_functions = {
            "Text.From": lambda col: f"CAST({col} AS VARCHAR)",
            "Text.Proper": lambda col: f"INITCAP({col})",
            "Text.BeforeDelimiter": lambda col, delim: f"SPLIT_PART({col}, '{delim}', 1)",
            "Text.AfterDelimiter": lambda col, delim: f"SPLIT_PART({col}, '{delim}', 2)",
            "Text.Contains": lambda col, text: f"{col} LIKE '%{text}%'",
            "Text.StartsWith": lambda col, text: f"{col} LIKE '{text}%'",
            "Text.EndsWith": lambda col, text: f"{col} LIKE '%{text}'",
            "Text.Length": lambda col: f"LENGTH({col})",
            "Text.Upper": lambda col: f"UPPER({col})",
            "Text.Lower": lambda col: f"LOWER({col})",
            "Text.Trim": lambda col: f"TRIM({col})",
            "Text.Replace": lambda col, old, new: f"REPLACE({col}, '{old}', '{new}')",
            "Text.Middle": lambda col, start, length: f"SUBSTRING({col}, {start}, {length})",
        }

    def translate(self, m_expr: str, table_name: str) -> TranslationResult:
        """Main translation entry point."""
        result = TranslationResult(success=False, sql="", confidence=0)

        try:
            # Extract and analyze steps
            steps = self._extract_steps(m_expr)
            source_info = self._identify_source(steps)

            if not source_info:
                result.errors.append(
                    f"Could not identify source table for {table_name}"
                )
                result.sql = (
                    f"-- Could not identify source table\nSELECT * FROM {table_name}"
                )
                return result

            # Check for native query
            if self._has_native_query(steps):
                result.sql = self._extract_native_query(steps, table_name)
                result.confidence = 90
                result.success = True
                result.metadata["translation_method"] = "native_query"
                return result

            # Translate operations
            sql_parts = self._translate_operations(steps, source_info, result)

            # Build final SQL
            result.sql = self._build_sql(sql_parts)

            # Clean up SQL
            result.sql = self._cleanup_sql(result.sql)

            # Calculate confidence
            result.confidence = self._calculate_confidence(result)

            # Set success if we have SQL
            if result.sql and result.confidence > 0:
                result.success = True

        except Exception as e:
            self.logger.error(f"Translation failed for {table_name}: {e}")
            if self.config.strict_mode:
                raise
            result.errors.append(str(e))
            result.sql = f"-- Translation failed: {e}\nSELECT * FROM {table_name}"
            result.confidence = 0.0

        return result

    def _extract_steps(self, m_expr: str) -> List[Dict[str, Any]]:
        """Extract transformation steps from M expression."""
        steps = []
        lines = m_expr.split("\n")

        current_step = None
        current_expr = []
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0

        for line in lines:
            line_stripped = line.strip()

            # Skip comments and empty lines
            if not line_stripped or line_stripped.startswith("//"):
                continue

            # Track depth for multi-line expressions
            paren_depth += line_stripped.count("(") - line_stripped.count(")")
            bracket_depth += line_stripped.count("[") - line_stripped.count("]")
            brace_depth += line_stripped.count("{") - line_stripped.count("}")

            # Check if this starts a new step
            if (
                "=" in line_stripped
                and paren_depth == 0
                and bracket_depth == 0
                and brace_depth == 0
            ):
                if not line_stripped.startswith("let") and not line_stripped.startswith(
                    "in"
                ):
                    # Save previous step
                    if current_step:
                        step_expr = " ".join(current_expr)
                        self.all_steps[current_step] = step_expr
                        steps.append({"name": current_step, "expression": step_expr})

                    # Parse new step
                    parts = line_stripped.split("=", 1)
                    if len(parts) == 2:
                        current_step = parts[0].strip().strip('#"').strip('"')
                        expr = parts[1].strip().rstrip(",")
                        current_expr = [expr]

                        # Update depth after extracting expression
                        paren_depth = expr.count("(") - expr.count(")")
                        bracket_depth = expr.count("[") - expr.count("]")
                        brace_depth = expr.count("{") - expr.count("}")
            elif current_step:
                # Continue current expression
                current_expr.append(line_stripped.rstrip(","))

        # Add last step
        if current_step:
            step_expr = " ".join(current_expr)
            self.all_steps[current_step] = step_expr
            steps.append({"name": current_step, "expression": step_expr})

        return steps

    def _identify_source(self, steps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Identify the source table from M steps."""
        for step in steps:
            expr = step["expression"]

            # Look for Snowflake source
            if "Snowflake.Databases" in expr:
                # Extract from View/Table reference
                match = re.search(r'Name="([^"]+)".*?Kind="(View|Table)"', expr)
                if match:
                    return {
                        "name": match.group(1),
                        "type": match.group(2),
                        "step": step["name"],
                        "is_snowflake": True,
                    }

            # Look for other sources
            if "Sql.Database" in expr or "Source =" in expr:
                # Try to extract table name
                return {
                    "name": step["name"],
                    "type": "Unknown",
                    "step": step["name"],
                    "is_snowflake": False,
                }

        return None

    def _translate_operations(
        self,
        steps: List[Dict[str, Any]],
        source_info: Dict[str, Any],
        result: TranslationResult,
    ) -> Dict[str, Any]:
        """Translate M operations to SQL components."""
        sql_parts = {
            "select": ["*"],
            "from": source_info["name"],
            "where": [],
            "join": [],
            "group_by": [],
            "having": [],
            "order_by": [],
            "limit": None,
            "unpivot": None,
            "pivot": None,
            "union_all": None,
            "with_ctes": [],
        }

        column_mapping = {}
        added_columns = []
        removed_columns = set()

        for i, step in enumerate(steps):
            expr = step["expression"]
            step_name = step["name"]

            # Skip source steps
            if step_name == source_info["step"] or self._is_source_step(expr):
                continue

            # Apply text function translations if enabled
            if self.config.enable_text_functions:
                expr = self._translate_text_functions(expr)

            # Table operations
            if "Table.SelectRows" in expr:
                conditions = self._extract_filter_conditions(expr)
                sql_parts["where"].extend(conditions)

            elif "Table.RenameColumns" in expr:
                renames = self._extract_column_renames(expr)
                column_mapping.update(renames)

            elif "Table.AddColumn" in expr:
                col_def = self._extract_added_column(expr)
                if col_def:
                    added_columns.append(col_def)

            elif "Table.RemoveColumns" in expr:
                cols = self._extract_column_list(expr)
                removed_columns.update(cols)

            elif "Table.SelectColumns" in expr:
                cols = self._extract_column_list(expr)
                sql_parts["select"] = cols

            elif "Table.Distinct" in expr:
                sql_parts["distinct"] = True

            elif "Table.Group" in expr:
                group_info = self._extract_group_by(expr)
                if group_info:
                    sql_parts["group_by"] = group_info["columns"]
                    if group_info.get("aggregations"):
                        added_columns.extend(group_info["aggregations"])

            elif "Table.Sort" in expr:
                sort_info = self._extract_sort(expr)
                if sort_info:
                    sql_parts["order_by"] = sort_info

            elif "Table.FirstN" in expr or "Table.MaxN" in expr:
                limit = self._extract_limit(expr)
                if limit:
                    sql_parts["limit"] = limit

            # Enhanced operations
            elif "Table.Unpivot" in expr and self.config.enable_unpivot:
                unpivot_info = self._translate_unpivot(expr)
                if unpivot_info:
                    sql_parts["unpivot"] = unpivot_info
                    result.enhanced_features_used.append("UNPIVOT")

            elif "Table.Pivot" in expr:
                pivot_info = self._translate_pivot(expr)
                if pivot_info:
                    sql_parts["pivot"] = pivot_info
                    result.enhanced_features_used.append("PIVOT")

            elif "Table.Combine" in expr and self.config.enable_union_all:
                union_info = self._translate_combine(expr)
                if union_info:
                    sql_parts["union_all"] = union_info
                    result.enhanced_features_used.append("UNION ALL")

            elif "Table.NestedJoin" in expr and self.config.enable_nested_joins:
                # Look ahead for ExpandTableColumn
                next_steps = steps[i + 1 : i + 3] if i + 1 < len(steps) else []
                join_info = self._translate_nested_join(expr, next_steps)
                if join_info:
                    sql_parts["join"].append(join_info)
                    result.enhanced_features_used.append("Nested JOIN")

            elif "Table.Join" in expr:
                join_info = self._translate_join(expr)
                if join_info:
                    sql_parts["join"].append(join_info)

            elif "Table.ReplaceValue" in expr:
                replace_def = self._extract_replace_value(expr)
                if replace_def:
                    added_columns.append(replace_def)

            elif "Table.DuplicateColumn" in expr:
                dup_def = self._extract_duplicate_column(expr)
                if dup_def:
                    added_columns.append(dup_def)

            # Track unsupported operations
            else:
                unsupported = self._check_unsupported_operation(expr)
                if unsupported:
                    result.warnings.append(f"Unsupported operation: {unsupported}")

        # Apply column operations
        sql_parts["column_mapping"] = column_mapping
        sql_parts["added_columns"] = added_columns
        sql_parts["removed_columns"] = removed_columns

        return sql_parts

    def _translate_text_functions(self, expr: str) -> str:
        """Translate all M Text functions to SQL."""
        # Text.From([column]) -> CAST(column AS VARCHAR)
        expr = re.sub(
            r"Text\.From\s*\(\s*\[([^\]]+)\]\s*\)", r"CAST(\1 AS VARCHAR)", expr
        )

        # Text.Proper([column]) -> INITCAP(column)
        expr = re.sub(r"Text\.Proper\s*\(\s*\[([^\]]+)\]\s*\)", r"INITCAP(\1)", expr)

        # Text.BeforeDelimiter([column], delimiter)
        expr = re.sub(
            r'Text\.BeforeDelimiter\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*\)',
            r"SPLIT_PART(\1, '\2', 1)",
            expr,
        )

        # Text.AfterDelimiter([column], delimiter)
        expr = re.sub(
            r'Text\.AfterDelimiter\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*\)',
            r"SPLIT_PART(\1, '\2', 2)",
            expr,
        )

        # Text.Contains([column], "text")
        expr = re.sub(
            r'Text\.Contains\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*\)',
            r"\1 LIKE '%\2%'",
            expr,
        )

        # Text.StartsWith([column], "text")
        expr = re.sub(
            r'Text\.StartsWith\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*\)',
            r"\1 LIKE '\2%'",
            expr,
        )

        # Text.EndsWith([column], "text")
        expr = re.sub(
            r'Text\.EndsWith\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*\)',
            r"\1 LIKE '%\2'",
            expr,
        )

        # Text.Length([column])
        expr = re.sub(r"Text\.Length\s*\(\s*\[([^\]]+)\]\s*\)", r"LENGTH(\1)", expr)

        # Text.Upper([column])
        expr = re.sub(r"Text\.Upper\s*\(\s*\[([^\]]+)\]\s*\)", r"UPPER(\1)", expr)

        # Text.Lower([column])
        expr = re.sub(r"Text\.Lower\s*\(\s*\[([^\]]+)\]\s*\)", r"LOWER(\1)", expr)

        # Text.Trim([column])
        expr = re.sub(r"Text\.Trim\s*\(\s*\[([^\]]+)\]\s*\)", r"TRIM(\1)", expr)

        # Text.Replace([column], old, new)
        expr = re.sub(
            r'Text\.Replace\s*\(\s*\[([^\]]+)\]\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
            r"REPLACE(\1, '\2', '\3')",
            expr,
        )

        return expr

    def _translate_unpivot(self, expr: str) -> Optional[Dict[str, Any]]:
        """Translate Table.Unpivot to SQL UNPIVOT."""
        if not self.config.enable_unpivot:
            return None

        # Pattern: Table.Unpivot(source, {"Col1", "Col2", ...}, "Attribute", "Value")
        match = re.search(
            r'Table\.Unpivot\s*\([^,]+,\s*\{([^}]+)\}\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\)',
            expr,
        )

        if match:
            columns_str = match.group(1)
            attribute_col = match.group(2)
            value_col = match.group(3)

            # Extract column names
            columns = [col.strip().strip('"') for col in columns_str.split(",")]

            # Generate UNPIVOT SQL
            unpivot_sql = f"""UNPIVOT({value_col} FOR {attribute_col} IN (
    {', '.join([f"{col} AS '{col}'" for col in columns])}
))"""

            return {
                "type": "unpivot",
                "sql": unpivot_sql,
                "columns": columns,
                "attribute": attribute_col,
                "value": value_col,
            }

        return None

    def _translate_combine(self, expr: str) -> Optional[Dict[str, Any]]:
        """Translate Table.Combine to UNION ALL."""
        if not self.config.enable_union_all:
            return None

        # Pattern: Table.Combine({table1, table2, table3})
        match = re.search(r"Table\.Combine\s*\(\s*\{([^}]+)\}\s*\)", expr)

        if match:
            tables_str = match.group(1)
            tables = []

            for table_ref in tables_str.split(","):
                table_ref = table_ref.strip().strip('#"').strip('"')
                tables.append(table_ref)

            # Build UNION ALL components
            union_parts = []
            for table in tables:
                if table in self.all_steps:
                    # Reference to a previous step - need to build its SQL
                    union_parts.append(f"-- From step: {table}")
                else:
                    # Direct table reference
                    union_parts.append(f"SELECT * FROM {table}")

            return {"type": "combine", "tables": tables, "sql_parts": union_parts}

        return None

    def _translate_nested_join(
        self, expr: str, next_steps: List[Dict]
    ) -> Optional[Dict[str, Any]]:
        """Translate Table.NestedJoin and ExpandTableColumn."""
        if not self.config.enable_nested_joins:
            return None

        # Pattern: Table.NestedJoin(table1, key1, table2, key2, "JoinedTable", joinKind)
        match = re.search(
            r'Table\.NestedJoin\s*\([^,]+,\s*(?:\{)?([^,}]+)(?:\})?,\s*([^,]+),\s*(?:\{)?([^,}]+)(?:\})?,\s*"([^"]+)"(?:,\s*([^)]+))?\)',
            expr,
        )

        if match:
            key1 = match.group(1).strip().strip('"')
            table2 = match.group(2).strip()
            key2 = match.group(3).strip().strip('"')
            join_name = match.group(4)
            join_kind = (
                match.group(5).strip() if match.group(5) else "JoinKind.LeftOuter"
            )

            # Determine join type
            join_type = "LEFT JOIN"
            if "Inner" in join_kind:
                join_type = "INNER JOIN"
            elif "RightOuter" in join_kind:
                join_type = "RIGHT JOIN"
            elif "FullOuter" in join_kind:
                join_type = "FULL OUTER JOIN"

            # Look for ExpandTableColumn
            expanded_cols = []
            for next_step in next_steps:
                if (
                    "Table.ExpandTableColumn" in next_step["expression"]
                    and join_name in next_step["expression"]
                ):
                    expand_match = re.search(
                        r'Table\.ExpandTableColumn\s*\([^,]+,\s*"'
                        + join_name
                        + r'"\s*,\s*\{([^}]+)\}',
                        next_step["expression"],
                    )
                    if expand_match:
                        cols_str = expand_match.group(1)
                        expanded_cols = [
                            col.strip().strip('"') for col in cols_str.split(",")
                        ]
                    break

            return {
                "type": "nested_join",
                "table2": table2,
                "key1": key1,
                "key2": key2,
                "join_type": join_type,
                "expanded_columns": expanded_cols,
                "sql": f"{join_type} {table2} ON base.{key1} = {table2}.{key2}",
            }

        return None

    def _build_sql(self, sql_parts: Dict[str, Any]) -> str:
        """Build final SQL from parts."""
        # Handle UNION ALL if present
        if sql_parts.get("union_all"):
            union_info = sql_parts["union_all"]
            return " UNION ALL ".join(union_info["sql_parts"])

        # Build standard SELECT query
        select_items = self._build_select_clause(sql_parts)

        # Build base query
        sql = []

        # WITH clause if needed
        if sql_parts.get("with_ctes"):
            cte_sql = ",\n".join(sql_parts["with_ctes"])
            sql.append(f"WITH {cte_sql}")

        # SELECT clause
        if sql_parts.get("distinct"):
            sql.append(f"SELECT DISTINCT\n  {', '.join(select_items)}")
        else:
            sql.append(f"SELECT\n  {', '.join(select_items)}")

        # FROM clause
        sql.append(f"FROM {sql_parts['from']}")

        # JOINs
        for join_info in sql_parts.get("join", []):
            sql.append(join_info["sql"])

        # WHERE clause
        if sql_parts.get("where"):
            where_conditions = self._optimize_where_conditions(sql_parts["where"])
            sql.append(f"WHERE {' AND '.join(where_conditions)}")

        # GROUP BY
        if sql_parts.get("group_by"):
            sql.append(f"GROUP BY {', '.join(sql_parts['group_by'])}")

        # HAVING
        if sql_parts.get("having"):
            sql.append(f"HAVING {' AND '.join(sql_parts['having'])}")

        # ORDER BY
        if sql_parts.get("order_by"):
            sql.append(f"ORDER BY {', '.join(sql_parts['order_by'])}")

        # Apply UNPIVOT if present
        result_sql = "\n".join(sql)
        if sql_parts.get("unpivot"):
            unpivot_info = sql_parts["unpivot"]
            result_sql = (
                f"SELECT * FROM ({result_sql}) AS pivoted\n{unpivot_info['sql']}"
            )

        # Apply PIVOT if present
        if sql_parts.get("pivot"):
            pivot_info = sql_parts["pivot"]
            result_sql = (
                f"SELECT * FROM ({result_sql}) AS unpivoted\n{pivot_info['sql']}"
            )

        # LIMIT
        if sql_parts.get("limit"):
            result_sql += f"\nLIMIT {sql_parts['limit']}"

        return result_sql

    def _cleanup_sql(self, sql: str) -> str:
        """Clean up the generated SQL."""
        # Remove remaining brackets
        sql = re.sub(r"\[([^\]]+)\]", r"\1", sql)

        # Fix quotes
        sql = re.sub(r'"([^"]*)"(?![,\)])', r"'\1'", sql)

        # Remove duplicate spaces
        sql = re.sub(r"\s+", " ", sql)

        # Fix line breaks
        sql = re.sub(r"\n\s*\n", "\n", sql)

        return sql.strip()

    def _calculate_confidence(self, result: TranslationResult) -> int:
        """Calculate confidence score for the translation."""
        confidence = 80  # Base confidence

        # Adjust based on features used
        if "UNPIVOT" in result.enhanced_features_used:
            confidence += 10
        if "UNION ALL" in result.enhanced_features_used:
            confidence += 10
        if "Nested JOIN" in result.enhanced_features_used:
            confidence += 5

        # Reduce for warnings and errors
        confidence -= len(result.warnings) * 10
        confidence -= len(result.errors) * 20

        # Cap between 0 and 100
        return max(0, min(100, confidence))

    # Helper methods (simplified versions shown)
    def _extract_filter_conditions(self, expr: str) -> List[str]:
        """Extract WHERE conditions from Table.SelectRows."""
        conditions = []

        # Simple equality
        for match in re.finditer(r'\[([^\]]+)\]\s*=\s*"([^"]+)"', expr):
            conditions.append(f"{match.group(1)} = '{match.group(2)}'")

        # Not equal
        for match in re.finditer(r'\[([^\]]+)\]\s*<>\s*"([^"]+)"', expr):
            conditions.append(f"{match.group(1)} <> '{match.group(2)}'")

        # NULL checks
        for match in re.finditer(r"\[([^\]]+)\]\s*<>\s*null", expr, re.IGNORECASE):
            conditions.append(f"{match.group(1)} IS NOT NULL")

        return conditions

    def _extract_column_renames(self, expr: str) -> Dict[str, str]:
        """Extract column rename mappings."""
        renames = {}
        for match in re.finditer(r'\{"([^"]+)",\s*"([^"]+)"\}', expr):
            renames[match.group(1)] = match.group(2)
        return renames

    def _extract_column_list(self, expr: str) -> List[str]:
        """Extract list of columns."""
        match = re.search(r"\{([^}]+)\}", expr)
        if match:
            return [c.strip().strip('"') for c in match.group(1).split(",")]
        return []

    def _extract_added_column(self, expr: str) -> Optional[Dict[str, str]]:
        """Extract added column definition."""
        match = re.search(
            r'Table\.AddColumn\s*\([^,]+,\s*"([^"]+)",\s*each\s+(.+?)\)', expr
        )
        if match:
            col_name = match.group(1)
            col_expr = self._translate_column_expression(match.group(2))
            return {"name": col_name, "expression": col_expr}
        return None

    def _translate_column_expression(self, expr: str) -> str:
        """Translate M column expression to SQL."""
        # Apply text functions
        if self.config.enable_text_functions:
            expr = self._translate_text_functions(expr)

        # Handle concatenation
        if "&" in expr:
            parts = []
            for part in expr.split("&"):
                part = part.strip()
                if part.startswith("[") and part.endswith("]"):
                    parts.append(part[1:-1])
                elif part.startswith('"') and part.endswith('"'):
                    parts.append(f"'{part[1:-1]}'")
                else:
                    parts.append(part)
            return f"CONCAT({', '.join(parts)})"

        # Handle if/then/else
        if " if " in expr.lower():
            match = re.search(
                r"if\s+(.+?)\s+then\s+(.+?)\s+else\s+(.+)", expr, re.IGNORECASE
            )
            if match:
                condition = re.sub(r"\[([^\]]+)\]", r"\1", match.group(1))
                true_val = re.sub(r"\[([^\]]+)\]", r"\1", match.group(2))
                false_val = re.sub(r"\[([^\]]+)\]", r"\1", match.group(3))
                return f"CASE WHEN {condition} THEN {true_val} ELSE {false_val} END"

        # Clean brackets
        expr = re.sub(r"\[([^\]]+)\]", r"\1", expr)

        # Fix string literals
        if expr.startswith('"') and expr.endswith('"'):
            return f"'{expr[1:-1]}'"

        return expr

    def _extract_replace_value(self, expr: str) -> Optional[Dict[str, str]]:
        """Extract replace value operation."""
        match = re.search(
            r'Table\.ReplaceValue\s*\([^,]+,\s*"([^"]+)",\s*"([^"]*)",\s*[^,]+,\s*\{"([^"]+)"\}',
            expr,
        )
        if match:
            return {
                "name": match.group(3),
                "expression": f"REPLACE({match.group(3)}, '{match.group(1)}', '{match.group(2)}')",
            }
        return None

    def _extract_duplicate_column(self, expr: str) -> Optional[Dict[str, str]]:
        """Extract duplicate column definition."""
        match = re.search(
            r'Table\.DuplicateColumn\s*\([^,]+,\s*"([^"]+)",\s*"([^"]+)"\)', expr
        )
        if match:
            return {"name": match.group(2), "expression": match.group(1)}
        return None

    def _is_source_step(self, expr: str) -> bool:
        """Check if this is a source step."""
        source_indicators = [
            "Source",
            "Database",
            "Schema",
            "Snowflake.Databases",
            "Sql.Database",
        ]
        return any(indicator in expr for indicator in source_indicators)

    def _has_native_query(self, steps: List[Dict[str, Any]]) -> bool:
        """Check if there's a native query."""
        return any("Value.NativeQuery" in step["expression"] for step in steps)

    def _extract_native_query(
        self, steps: List[Dict[str, Any]], table_name: str
    ) -> str:
        """Extract native query from steps."""
        # This would need more sophisticated parsing
        return f"-- Native query detected for {table_name}\n-- Manual extraction needed"

    def _check_unsupported_operation(self, expr: str) -> Optional[str]:
        """Check for unsupported operations."""
        unsupported = [
            "Table.Buffer",
            "Table.Cache",
            "List.Generate",
            "Table.FromList",
            "Table.TransformColumnTypes",
            "Table.Schema",
        ]
        for op in unsupported:
            if op in expr:
                return op
        return None

    def _optimize_where_conditions(self, conditions: List[str]) -> List[str]:
        """Optimize WHERE conditions to fix AND/OR logic."""
        # Group conditions by column
        column_conditions = {}
        for condition in conditions:
            # Extract column name
            match = re.match(r"(\w+)\s*([=<>]+|IS|LIKE)", condition)
            if match:
                col = match.group(1)
                if col not in column_conditions:
                    column_conditions[col] = []
                column_conditions[col].append(condition)

        # Optimize conditions
        optimized = []
        for col, conds in column_conditions.items():
            if len(conds) > 1 and all("=" in c for c in conds):
                # Multiple equality conditions on same column -> use IN
                values = [c.split("'")[1] for c in conds if "'" in c]
                if values:
                    values_str = ", ".join([f"'{v}'" for v in values])
                    optimized.append(f"{col} IN ({values_str})")
            else:
                optimized.extend(conds)

        return optimized if optimized else conditions

    def _build_select_clause(self, sql_parts: Dict[str, Any]) -> List[str]:
        """Build SELECT clause items."""
        select_items = []

        if sql_parts["select"] == ["*"]:
            select_items.append("*")

            # Add renamed columns
            for old, new in sql_parts.get("column_mapping", {}).items():
                if old not in sql_parts.get("removed_columns", set()):
                    select_items.append(f"{old} AS {new}")
        else:
            # Specific columns
            for col in sql_parts["select"]:
                if col not in sql_parts.get("removed_columns", set()):
                    if col in sql_parts.get("column_mapping", {}):
                        select_items.append(
                            f"{col} AS {sql_parts['column_mapping'][col]}"
                        )
                    else:
                        select_items.append(col)

        # Add new columns
        for col_def in sql_parts.get("added_columns", []):
            select_items.append(f"{col_def['expression']} AS {col_def['name']}")

        return select_items if select_items else ["*"]

    def _extract_group_by(self, expr: str) -> Optional[Dict[str, Any]]:
        """Extract GROUP BY information."""
        # Simplified - would need more sophisticated parsing
        match = re.search(r"Table\.Group\s*\([^,]+,\s*\{([^}]+)\}", expr)
        if match:
            columns = [c.strip().strip('"') for c in match.group(1).split(",")]
            return {"columns": columns}
        return None

    def _extract_sort(self, expr: str) -> List[str]:
        """Extract ORDER BY information."""
        # Simplified
        sort_cols = []
        if "Order.Ascending" in expr:
            match = re.search(r"\[([^\]]+)\].*Order\.Ascending", expr)
            if match:
                sort_cols.append(f"{match.group(1)} ASC")
        if "Order.Descending" in expr:
            match = re.search(r"\[([^\]]+)\].*Order\.Descending", expr)
            if match:
                sort_cols.append(f"{match.group(1)} DESC")
        return sort_cols

    def _extract_limit(self, expr: str) -> Optional[int]:
        """Extract LIMIT value."""
        match = re.search(r"Table\.(?:FirstN|MaxN)\s*\([^,]+,\s*(\d+)", expr)
        if match:
            return int(match.group(1))
        return None

    def _translate_join(self, expr: str) -> Optional[Dict[str, Any]]:
        """Translate Table.Join."""
        # Simplified
        match = re.search(r"Table\.Join\s*\(([^,]+),\s*([^,]+)", expr)
        if match:
            return {
                "type": "join",
                "sql": f"-- Table.Join detected, needs manual review",
            }
        return None

    def _translate_pivot(self, expr: str) -> Optional[Dict[str, Any]]:
        """Translate Table.Pivot."""
        # This would need implementation
        return None


class DAXToSQLTranslator:
    """Unified DAX to SQL translator with enhanced features."""

    def __init__(self, config: Optional[TranslationConfig] = None):
        self.config = config or TranslationConfig()
        self.logger = logging.getLogger(__name__)

    def translate_column(
        self, column_def: Dict[str, Any], table_name: str
    ) -> TranslationResult:
        """Translate a DAX calculated column to SQL."""
        try:
            dax_expr = column_def.get("expression", "")
            column_name = column_def.get("name", "")

            if not dax_expr:
                return TranslationResult(
                    success=False,
                    sql="",
                    confidence=0,
                    errors=["No DAX expression found"],
                )

            # Clean and translate the DAX expression
            sql_expr = self._translate_dax_expression(dax_expr, table_name)

            # Check for remaining DAX functions
            remaining_dax = self._check_remaining_dax(sql_expr)

            confidence = 100 if not remaining_dax else 50
            warnings = (
                [f"Remaining DAX: {', '.join(remaining_dax)}"] if remaining_dax else []
            )

            return TranslationResult(
                success=True,
                sql=f"{sql_expr} AS {column_name}",
                confidence=confidence,
                warnings=warnings,
            )

        except Exception as e:
            self.logger.error(f"Error translating DAX column {column_name}: {e}")
            return TranslationResult(
                success=False, sql="", confidence=0, errors=[str(e)]
            )

    def translate_table(self, table_def: Dict[str, Any]) -> TranslationResult:
        """Translate a DAX calculated table to SQL."""
        try:
            dax_expr = table_def.get("expression", "")
            table_name = table_def.get("name", "")

            # Try to detect common patterns
            if self.config.enable_calculated_table_patterns:
                pattern_result = self._detect_table_pattern(dax_expr, table_name)
                if pattern_result:
                    return pattern_result

            # Otherwise, provide a template
            return TranslationResult(
                success=False,
                sql=f"-- Calculated table {table_name} needs manual translation\n-- DAX: {dax_expr[:200]}",
                confidence=0,
                warnings=["Calculated table requires manual translation"],
            )

        except Exception as e:
            self.logger.error(f"Error translating DAX table {table_name}: {e}")
            return TranslationResult(
                success=False, sql="", confidence=0, errors=[str(e)]
            )

    def _translate_dax_expression(self, dax: str, table_name: str) -> str:
        """Translate DAX expression to SQL."""
        sql = dax

        # LOOKUPVALUE translations
        if self.config.enable_lookupvalue_translation:
            sql = self._translate_lookupvalue(sql, table_name)

        # IF statements
        sql = self._translate_if_statements(sql)

        # SWITCH statements
        sql = self._translate_switch_statements(sql)

        # Date functions
        sql = self._translate_date_functions(sql)

        # Text functions
        sql = self._translate_text_functions(sql)

        # Math functions
        sql = self._translate_math_functions(sql)

        # Clean up remaining brackets
        sql = re.sub(r"\[([^\]]+)\]", r"\1", sql)

        # Fix quotes
        sql = sql.replace('"', "'")

        return sql

    def _translate_lookupvalue(self, dax: str, table_name: str) -> str:
        """Translate LOOKUPVALUE to subquery."""
        pattern = r"LOOKUPVALUE\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)"

        def replace_lookupvalue(match):
            result_col = match.group(1).strip()
            search_col = match.group(2).strip()
            search_val = match.group(3).strip()

            # Extract table and column names
            result_parts = result_col.replace("[", "").replace("]", "").split(".")
            search_parts = search_col.replace("[", "").replace("]", "").split(".")

            if len(result_parts) == 2 and len(search_parts) == 2:
                lookup_table = result_parts[0]
                result_column = result_parts[1]
                search_column = search_parts[1]

                # Create subquery
                return f"(SELECT MAX({result_column}) FROM {lookup_table} WHERE {search_column} = {search_val})"

            return match.group(0)  # Return original if can't parse

        return re.sub(pattern, replace_lookupvalue, dax)

    def _translate_if_statements(self, dax: str) -> str:
        """Translate IF to CASE WHEN."""
        pattern = r"IF\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)"

        def replace_if(match):
            condition = match.group(1).strip()
            true_val = match.group(2).strip()
            false_val = match.group(3).strip()
            return f"CASE WHEN {condition} THEN {true_val} ELSE {false_val} END"

        return re.sub(pattern, replace_if, dax, flags=re.IGNORECASE)

    def _translate_switch_statements(self, dax: str) -> str:
        """Translate SWITCH to CASE."""
        pattern = r"SWITCH\s*\(([^,]+)((?:,\s*[^,]+,\s*[^,]+)*),\s*([^)]+)\)"

        def replace_switch(match):
            expr = match.group(1).strip()
            pairs = match.group(2)
            default = match.group(3).strip()

            case_stmt = f"CASE {expr}"

            # Parse value pairs
            pair_pattern = r",\s*([^,]+),\s*([^,]+)"
            for pair_match in re.finditer(pair_pattern, pairs):
                test_val = pair_match.group(1).strip()
                result_val = pair_match.group(2).strip()
                case_stmt += f" WHEN {test_val} THEN {result_val}"

            case_stmt += f" ELSE {default} END"
            return case_stmt

        return re.sub(pattern, replace_switch, dax, flags=re.IGNORECASE)

    def _translate_date_functions(self, dax: str) -> str:
        """Translate DAX date functions to SQL."""
        replacements = [
            (r"TODAY\s*\(\)", "CURRENT_DATE()"),
            (r"NOW\s*\(\)", "CURRENT_TIMESTAMP()"),
            (r"YEAR\s*\(([^)]+)\)", r"YEAR(\1)"),
            (r"MONTH\s*\(([^)]+)\)", r"MONTH(\1)"),
            (r"DAY\s*\(([^)]+)\)", r"DAY(\1)"),
            (r"DATEDIFF\s*\(([^,]+),\s*([^,]+),\s*DAY\)", r"DATEDIFF('day', \1, \2)"),
            (
                r"DATEDIFF\s*\(([^,]+),\s*([^,]+),\s*MONTH\)",
                r"DATEDIFF('month', \1, \2)",
            ),
            (r"DATEDIFF\s*\(([^,]+),\s*([^,]+),\s*YEAR\)", r"DATEDIFF('year', \1, \2)"),
        ]

        for pattern, replacement in replacements:
            dax = re.sub(pattern, replacement, dax, flags=re.IGNORECASE)

        return dax

    def _translate_text_functions(self, dax: str) -> str:
        """Translate DAX text functions to SQL."""
        replacements = [
            (r"CONCATENATE\s*\(([^,]+),\s*([^)]+)\)", r"CONCAT(\1, \2)"),
            (r"UPPER\s*\(([^)]+)\)", r"UPPER(\1)"),
            (r"LOWER\s*\(([^)]+)\)", r"LOWER(\1)"),
            (r"TRIM\s*\(([^)]+)\)", r"TRIM(\1)"),
            (r"LEN\s*\(([^)]+)\)", r"LENGTH(\1)"),
            (r"LEFT\s*\(([^,]+),\s*([^)]+)\)", r"LEFT(\1, \2)"),
            (r"RIGHT\s*\(([^,]+),\s*([^)]+)\)", r"RIGHT(\1, \2)"),
            (r"MID\s*\(([^,]+),\s*([^,]+),\s*([^)]+)\)", r"SUBSTRING(\1, \2, \3)"),
            (
                r"SEARCH\s*\(([^,]+),\s*([^,]+)(?:,\s*[^,]+)?(?:,\s*([^)]+))?\)",
                lambda m: f"IFF(POSITION({m.group(1)}, {m.group(2)}) > 0, POSITION({m.group(1)}, {m.group(2)}), {m.group(3) if m.group(3) else '0'})",
            ),
        ]

        for pattern, replacement in replacements:
            dax = re.sub(pattern, replacement, dax, flags=re.IGNORECASE)

        return dax

    def _translate_math_functions(self, dax: str) -> str:
        """Translate DAX math functions to SQL."""
        replacements = [
            (r"ROUND\s*\(([^,]+),\s*([^)]+)\)", r"ROUND(\1, \2)"),
            (r"CEILING\s*\(([^,]+),\s*([^)]+)\)", r"CEIL(\1 / \2) * \2"),
            (r"FLOOR\s*\(([^,]+),\s*([^)]+)\)", r"FLOOR(\1 / \2) * \2"),
            (r"ABS\s*\(([^)]+)\)", r"ABS(\1)"),
            (r"POWER\s*\(([^,]+),\s*([^)]+)\)", r"POWER(\1, \2)"),
            (r"SQRT\s*\(([^)]+)\)", r"SQRT(\1)"),
        ]

        for pattern, replacement in replacements:
            dax = re.sub(pattern, replacement, dax, flags=re.IGNORECASE)

        return dax

    def _check_remaining_dax(self, sql: str) -> List[str]:
        """Check for remaining DAX functions."""
        dax_functions = [
            "CALCULATE",
            "CALCULATETABLE",
            "FILTER",
            "ALL",
            "ALLEXCEPT",
            "RELATED",
            "RELATEDTABLE",
            "SUMMARIZE",
            "ADDCOLUMNS",
            "SELECTCOLUMNS",
            "EARLIER",
            "EARLIEST",
            "VALUES",
            "DISTINCT",
            "COUNTROWS",
            "BLANK",
            "ISBLANK",
            "HASONEVALUE",
            "SELECTEDVALUE",
        ]

        remaining = []
        for func in dax_functions:
            if re.search(rf"\b{func}\s*\(", sql, re.IGNORECASE):
                remaining.append(func)

        return remaining

    def _detect_table_pattern(
        self, dax: str, table_name: str
    ) -> Optional[TranslationResult]:
        """Detect common calculated table patterns."""
        # Parameter table pattern
        if "DATATABLE" in dax or "{(" in dax:
            return self._create_parameter_table_sql(dax, table_name)

        # UNION pattern
        if "UNION" in dax:
            return self._create_union_table_sql(dax, table_name)

        # FILTER pattern
        if dax.strip().startswith("FILTER"):
            return self._create_filter_table_sql(dax, table_name)

        # SUMMARIZE pattern
        if "SUMMARIZE" in dax:
            return self._create_summarize_table_sql(dax, table_name)

        return None

    def _create_parameter_table_sql(
        self, dax: str, table_name: str
    ) -> TranslationResult:
        """Create SQL for parameter tables."""
        # Try to extract values
        values_match = re.findall(r"\{([^}]+)\}", dax)

        if values_match:
            sql = f"CREATE OR REPLACE VIEW SEMANTIC.V_{table_name} AS\n"
            sql += "SELECT * FROM (VALUES\n"
            sql += "  -- Extracted values need manual formatting\n"
            for value_str in values_match[:5]:  # Show first 5 as example
                sql += f"  -- {value_str}\n"
            sql += ") AS t(column1, column2, ...)"

            return TranslationResult(
                success=True,
                sql=sql,
                confidence=30,
                warnings=["Parameter table pattern detected - needs manual completion"],
            )

        return None

    def _create_union_table_sql(self, dax: str, table_name: str) -> TranslationResult:
        """Create SQL for UNION tables."""
        # Extract table names
        tables = re.findall(r"([A-Z_][A-Z0-9_]*)", dax)
        tables = [t for t in tables if t not in ["UNION", "ALL"]]

        if tables:
            sql = f"CREATE OR REPLACE VIEW SEMANTIC.V_{table_name} AS\n"
            sql += f"SELECT * FROM {tables[0]}"
            for table in tables[1:]:
                sql += f"\nUNION ALL\nSELECT * FROM {table}"

            return TranslationResult(
                success=True,
                sql=sql,
                confidence=80,
                warnings=["UNION pattern detected - verify table names"],
            )

        return None

    def _create_filter_table_sql(self, dax: str, table_name: str) -> TranslationResult:
        """Create SQL for FILTER tables."""
        match = re.search(r"FILTER\s*\(([^,]+),\s*(.+)\)", dax)

        if match:
            source_table = match.group(1).strip()
            condition = match.group(2).strip()

            # Translate the condition
            sql_condition = self._translate_dax_expression(condition, table_name)

            sql = f"CREATE OR REPLACE VIEW SEMANTIC.V_{table_name} AS\n"
            sql += f"SELECT * FROM {source_table}\n"
            sql += f"WHERE {sql_condition}"

            return TranslationResult(
                success=True,
                sql=sql,
                confidence=70,
                warnings=["FILTER pattern detected - verify WHERE clause"],
            )

        return None

    def _create_summarize_table_sql(
        self, dax: str, table_name: str
    ) -> TranslationResult:
        """Create SQL for SUMMARIZE tables."""
        # This is complex and would need sophisticated parsing
        sql = f"CREATE OR REPLACE VIEW SEMANTIC.V_{table_name} AS\n"
        sql += "-- SUMMARIZE pattern detected\n"
        sql += "-- Manual translation required for:\n"
        sql += f"-- {dax[:200]}"

        return TranslationResult(
            success=False,
            sql=sql,
            confidence=10,
            warnings=["SUMMARIZE requires manual translation"],
        )


class UnifiedTranslator:
    """Main translator that combines M and DAX translation."""

    def __init__(self, config: Optional[TranslationConfig] = None):
        self.config = config or TranslationConfig()
        self.m_translator = MToSQLTranslator(config)
        self.dax_translator = DAXToSQLTranslator(config)
        self.logger = logging.getLogger(__name__)

    def translate_table(self, table_def: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a complete table definition."""
        table_name = table_def.get("name", "")
        result = {
            "name": table_name,
            "success": False,
            "sql": "",
            "confidence": 0,
            "warnings": [],
            "errors": [],
            "type": "unknown",
        }

        try:
            # Check if it's a calculated table
            calc_table_expr = table_def.get("calc_table_expression")
            if calc_table_expr:
                # It's a calculated table
                dax_result = self.dax_translator.translate_table(
                    {"name": table_name, "expression": calc_table_expr}
                )
                result.update(
                    {
                        "success": dax_result.success,
                        "sql": dax_result.sql,
                        "confidence": dax_result.confidence,
                        "warnings": dax_result.warnings,
                        "errors": dax_result.errors,
                        "type": "calculated",
                    }
                )
            else:
                # Translate M expression from partitions
                partitions = table_def.get("partitions", [])
                m_expr = ""
                if partitions and len(partitions) > 0:
                    m_expr = partitions[0].get("m_expression", "")

                if m_expr:
                    m_result = self.m_translator.translate(m_expr, table_name)

                    # Add calculated columns if any
                    calculated_columns = table_def.get("calc_columns", [])
                    column_sql = []

                    for col in calculated_columns:
                        col_result = self.dax_translator.translate_column(
                            col, table_name
                        )
                        if col_result.success:
                            column_sql.append(col_result.sql)
                        else:
                            result["warnings"].append(
                                f"Column {col.get('name')}: {col_result.warnings}"
                            )

                    # Combine M and DAX translations
                    if m_result.success:
                        if column_sql:
                            # Add calculated columns to SELECT
                            base_sql = m_result.sql
                            if "SELECT *" in base_sql:
                                columns_str = ",\n  ".join(column_sql)
                                enhanced_sql = base_sql.replace(
                                    "SELECT *", f"SELECT *,\n  {columns_str}"
                                )
                            else:
                                # More complex - would need proper SQL parsing
                                columns_str = ",\n  ".join(column_sql)
                                enhanced_sql = f"WITH base AS ({base_sql})\n"
                                enhanced_sql += f"SELECT base.*,\n  {columns_str}\n"
                                enhanced_sql += "FROM base"

                            result["sql"] = enhanced_sql
                        else:
                            result["sql"] = m_result.sql

                        result.update(
                            {
                                "success": m_result.success,
                                "confidence": m_result.confidence,
                                "warnings": result["warnings"] + m_result.warnings,
                                "errors": m_result.errors,
                                "type": "query",
                            }
                        )
                    else:
                        result["errors"] = m_result.errors

        except Exception as e:
            self.logger.error(f"Error translating table {table_name}: {e}")
            result["errors"].append(str(e))

        return result
