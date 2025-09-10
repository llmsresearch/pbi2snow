"""Extract M expressions, DAX formulas, and relationships from Power BI model files."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional


def load_bim(path: str) -> Dict[str, Any]:
    """Load a BIM (Business Intelligence Model) file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def iter_tables(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Iterate through tables in the model."""
    return model.get("model", {}).get("tables", [])


def get_partitions(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get partitions from a table."""
    return table.get("partitions", [])


def get_relationships(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get relationships from the model."""
    return model.get("model", {}).get("relationships", [])


def get_calc_columns(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get calculated columns from a table."""
    columns = []
    for c in table.get("columns", []):
        if c.get("type", "").lower() == "calculated":
            columns.append(c)
    return columns


def get_calc_table_expression(table: Dict[str, Any]) -> Optional[str]:
    """Get the DAX expression for a calculated table."""
    for p in table.get("partitions", []):
        src = p.get("source", {})
        if src.get("type", "").lower() == "calculated":
            return src.get("expression")
    return None


def extract_m_expression(partition: Dict[str, Any]) -> Optional[str]:
    """Extract M expression from a partition."""
    source = partition.get("source", {})
    if source.get("type", "").lower() == "m":
        expr = source.get("expression", [])
        if isinstance(expr, list):
            return "\n".join(expr)
        return expr
    return None


def collect(model_path: str) -> Dict[str, Any]:
    """Collect all relevant information from the model."""
    model = load_bim(model_path)
    out = {
        "tables": [],
        "relationships": get_relationships(model)
    }
    
    for t in iter_tables(model):
        tbl = {
            "name": t["name"],
            "partitions": [],
            "calc_columns": [],
            "calc_table_expression": get_calc_table_expression(t),
            "regular_columns": []
        }
        
        # Extract regular columns
        for c in t.get("columns", []):
            if c.get("type", "").lower() != "calculated":
                tbl["regular_columns"].append({
                    "name": c.get("name"),
                    "dataType": c.get("dataType"),
                    "sourceColumn": c.get("sourceColumn")
                })
        
        # Extract partitions with M expressions
        for p in get_partitions(t):
            m_expr = extract_m_expression(p)
            if m_expr:
                tbl["partitions"].append({
                    "name": p.get("name"),
                    "mode": p.get("mode", "import"),
                    "m_expression": m_expr
                })
        
        # Extract calculated columns with DAX
        for c in get_calc_columns(t):
            expr = c.get("expression", "")
            if isinstance(expr, list):
                expr = "\n".join(expr)
            tbl["calc_columns"].append({
                "name": c["name"],
                "dataType": c.get("dataType", "string"),
                "dax": expr
            })
        
        out["tables"].append(tbl)
    
    return out


def analyze_m_operations(m_expression: str) -> Dict[str, Any]:
    """Analyze M expression to identify operations used."""
    operations = {
        "source": None,
        "transforms": [],
        "has_native_query": False,
        "is_snowflake": False
    }
    
    lines = m_expression.split('\n')
    for line in lines:
        line = line.strip()
        
        # Check for Snowflake source
        if "Snowflake.Databases" in line:
            operations["is_snowflake"] = True
            operations["source"] = "Snowflake"
        
        # Check for common M operations
        m_ops = [
            "Table.SelectRows", "Table.RemoveColumns", "Table.RenameColumns",
            "Table.AddColumn", "Table.ReplaceValue", "Table.Distinct",
            "Table.Group", "Table.Join", "Table.NestedJoin",
            "Table.ExpandTableColumn", "Table.Unpivot", "Table.Pivot",
            "Table.Combine", "Table.FirstN", "Table.Skip",
            "Table.DuplicateColumn", "Table.SelectColumns"
        ]
        
        for op in m_ops:
            if op in line:
                operations["transforms"].append({
                    "operation": op,
                    "line": line
                })
        
        # Check for native query
        if "Value.NativeQuery" in line:
            operations["has_native_query"] = True
    
    return operations


if __name__ == "__main__":
    # Test extraction
    import json
    
    model_data = collect("input/Model.bim")
    
    print("Tables found:", len(model_data["tables"]))
    for table in model_data["tables"]:
        print(f"\nTable: {table['name']}")
        if table["partitions"]:
            print(f"  - Partitions: {len(table['partitions'])}")
            for p in table["partitions"]:
                ops = analyze_m_operations(p["m_expression"])
                print(f"    - {p['name']}: {len(ops['transforms'])} M operations")
        if table["calc_columns"]:
            print(f"  - Calculated columns: {len(table['calc_columns'])}")
        if table["calc_table_expression"]:
            print(f"  - Is calculated table: Yes")