#!/usr/bin/env python3
"""
Unified CLI for Power BI to Snowflake translation.
Production-ready with configuration options.
"""

import click
import json
import logging
from pathlib import Path
from typing import Optional
import sys
import os

from . import extract
from .translator import UnifiedTranslator, TranslationConfig, TranslationMode
from .sqlgen import SnowflakeViewGenerator as SQLViewGenerator


def setup_logging(verbose: bool):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def create_manifest(results, output_dir):
    """Create a manifest file with translation results."""
    manifest = {
        "total_tables": len(results),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "by_confidence": {},
        "by_type": {},
        "tables": [],
    }

    # Group by confidence
    for result in results:
        confidence = result.get("confidence", 0)
        if confidence >= 80:
            level = "high"
        elif confidence >= 50:
            level = "medium"
        else:
            level = "low"

        if level not in manifest["by_confidence"]:
            manifest["by_confidence"][level] = []
        manifest["by_confidence"][level].append(result["name"])

    # Group by type
    for result in results:
        table_type = result.get("type", "unknown")
        if table_type not in manifest["by_type"]:
            manifest["by_type"][table_type] = []
        manifest["by_type"][table_type].append(result["name"])

    # Add table details
    for result in results:
        manifest["tables"].append(
            {
                "name": result["name"],
                "success": result["success"],
                "confidence": result.get("confidence", 0),
                "type": result.get("type", "unknown"),
                "warnings": result.get("warnings", []),
                "errors": result.get("errors", []),
            }
        )

    # Write manifest
    manifest_path = Path(output_dir) / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def print_summary(manifest):
    """Print a summary of translation results."""
    click.echo("\n" + "=" * 60)
    click.echo("Translation Summary")
    click.echo("=" * 60)

    total = manifest["total_tables"]
    successful = manifest["successful"]
    failed = manifest["failed"]

    click.echo(f"Total tables: {total}")
    click.echo(f"Successful: {successful} ({successful/total*100:.1f}%)")
    click.echo(f"Failed: {failed} ({failed/total*100:.1f}%)")

    click.echo("\nBy Confidence Level:")
    for level in ["high", "medium", "low"]:
        tables = manifest["by_confidence"].get(level, [])
        if tables:
            click.echo(f"  {level.capitalize()}: {len(tables)} tables")

    click.echo("\nBy Type:")
    for table_type, tables in manifest["by_type"].items():
        click.echo(f"  {table_type.capitalize()}: {len(tables)} tables")

    # Show problematic tables
    problem_tables = [
        t for t in manifest["tables"] if not t["success"] or t["confidence"] < 50
    ]
    if problem_tables:
        click.echo("\nTables needing review:")
        for table in problem_tables[:10]:  # Show first 10
            click.echo(f"  - {table['name']} (confidence: {table['confidence']}%)")
            if table["errors"]:
                click.echo(f"    Error: {table['errors'][0]}")

        if len(problem_tables) > 10:
            click.echo(f"  ... and {len(problem_tables) - 10} more")

    click.echo("\n" + "=" * 60)


@click.command()
@click.option(
    "--bim-file",
    default="Model.bim",
    help="Path to the Power BI model file (BIM/TMSL format)",
)
@click.option(
    "--output-dir", default="out_unified", help="Output directory for SQL views"
)
@click.option(
    "--target-schema", default="SEMANTIC", help="Target Snowflake schema name"
)
@click.option(
    "--mode",
    type=click.Choice(["basic", "enhanced", "aggressive"], case_sensitive=False),
    default="enhanced",
    help="Translation mode: basic (conservative), enhanced (recommended), aggressive (experimental)",
)
@click.option(
    "--enable-unpivot/--disable-unpivot",
    default=True,
    help="Enable UNPIVOT translation",
)
@click.option(
    "--enable-union-all/--disable-union-all",
    default=True,
    help="Enable Table.Combine to UNION ALL translation",
)
@click.option(
    "--enable-nested-joins/--disable-nested-joins",
    default=True,
    help="Enable Table.NestedJoin translation",
)
@click.option(
    "--enable-text-functions/--disable-text-functions",
    default=True,
    help="Enable Text function translations",
)
@click.option(
    "--enable-lookupvalue/--disable-lookupvalue",
    default=True,
    help="Enable LOOKUPVALUE translation",
)
@click.option(
    "--enable-calculated-patterns/--disable-calculated-patterns",
    default=True,
    help="Enable calculated table pattern detection",
)
@click.option(
    "--parse-m-expressions/--skip-m-parsing",
    default=True,
    help="Parse M expressions with Node.js parser",
)
@click.option(
    "--optimize-where/--no-optimize-where",
    default=True,
    help="Optimize WHERE clause AND/OR logic",
)
@click.option(
    "--clean-brackets/--keep-brackets",
    default=True,
    help="Remove bracket references from column names",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option(
    "--dry-run", is_flag=True, help="Run without writing files (preview only)"
)
@click.option(
    "--filter-tables",
    help="Comma-separated list of table names to process (process all if not specified)",
)
@click.option("--exclude-tables", help="Comma-separated list of table names to exclude")
@click.option(
    "--confidence-threshold",
    type=int,
    default=0,
    help="Only output views with confidence >= threshold (0-100)",
)
def main(
    bim_file,
    output_dir,
    target_schema,
    mode,
    enable_unpivot,
    enable_union_all,
    enable_nested_joins,
    enable_text_functions,
    enable_lookupvalue,
    enable_calculated_patterns,
    parse_m_expressions,
    optimize_where,
    clean_brackets,
    verbose,
    dry_run,
    filter_tables,
    exclude_tables,
    confidence_threshold,
):
    """
    Power BI to Snowflake SQL Translator - Unified Production Version

    Translates Power BI models (BIM/TMSL format) to Snowflake SQL views.
    Supports both M expressions and DAX calculated columns/tables.

    Examples:

        # Basic usage with defaults (recommended)
        python -m pbi2snow.cli_unified

        # Conservative mode for production
        python -m pbi2snow.cli_unified --mode basic --confidence-threshold 80

        # Process specific tables only
        python -m pbi2snow.cli_unified --filter-tables "FCT_SALES,DIM_CUSTOMER"

        # Dry run to preview without writing files
        python -m pbi2snow.cli_unified --dry-run --verbose

        # Aggressive mode for maximum automation
        python -m pbi2snow.cli_unified --mode aggressive --optimize-where
    """

    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    click.echo(f"Power BI to Snowflake Translator - Unified Version")
    click.echo(f"Mode: {mode}")
    click.echo(f"Input: {bim_file}")
    click.echo(f"Output: {output_dir}/")

    # Determine translation mode
    translation_mode = {
        "basic": TranslationMode.BASIC,
        "enhanced": TranslationMode.ENHANCED,
        "aggressive": TranslationMode.AGGRESSIVE,
    }.get(mode.lower(), TranslationMode.ENHANCED)

    # Create configuration
    config = TranslationConfig(
        mode=translation_mode,
        enable_unpivot=enable_unpivot,
        enable_union_all=enable_union_all,
        enable_nested_joins=enable_nested_joins,
        enable_text_functions=enable_text_functions,
        enable_lookupvalue_translation=enable_lookupvalue,
        enable_calculated_table_patterns=enable_calculated_patterns,
        parse_m_expressions=parse_m_expressions,
        optimize_where_conditions=optimize_where,
        clean_bracket_references=clean_brackets,
    )

    # Parse filter/exclude lists
    filter_set = set(filter_tables.split(",")) if filter_tables else None
    exclude_set = set(exclude_tables.split(",")) if exclude_tables else set()

    try:
        # Extract model
        click.echo("\nExtracting Power BI model...")
        model = extract.collect(bim_file)

        total_tables = len(model["tables"])
        click.echo(f"Found {total_tables} tables in model")

        # Filter tables
        tables_to_process = []
        for table in model["tables"]:
            table_name = table.get("name", "")

            # Apply filters
            if exclude_set and table_name in exclude_set:
                continue
            if filter_set and table_name not in filter_set:
                continue

            tables_to_process.append(table)

        click.echo(f"Processing {len(tables_to_process)} tables after filtering")

        # Create translator
        translator = UnifiedTranslator(config)

        # Translate tables
        click.echo("\nTranslating tables...")
        results = []

        with click.progressbar(tables_to_process, label="Translating") as tables:
            for table in tables:
                result = translator.translate_table(table)

                # Apply confidence threshold
                if result.get("confidence", 0) >= confidence_threshold:
                    results.append(result)

                if verbose and not result["success"]:
                    logger.warning(
                        f"Failed to translate {table['name']}: {result.get('errors', [])}"
                    )

        # Create output directory
        if not dry_run:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            views_path = output_path / "views"
            views_path.mkdir(exist_ok=True)

            # Generate SQL files
            click.echo(f"\nGenerating SQL views...")
            generator = SQLViewGenerator(target_schema)

            for result in results:
                if result["success"] and result["sql"]:
                    view_sql = generator.generate_view(
                        result["name"], result["sql"], result.get("warnings", [])
                    )

                    # Write SQL file
                    sql_file = views_path / f"V_{result['name']}.sql"
                    with open(sql_file, "w") as f:
                        f.write(view_sql)

            # Create manifest
            manifest = create_manifest(results, output_dir)

            # Write combined SQL file
            combined_file = output_path / "all_views.sql"
            with open(combined_file, "w") as f:
                f.write(f"-- Power BI to Snowflake Views\n")
                f.write(f"-- Generated with mode: {mode}\n")
                f.write(
                    f"-- Total views: {len([r for r in results if r['success']])}\n\n"
                )

                for result in results:
                    if result["success"] and result["sql"]:
                        view_sql = generator.generate_view(
                            result["name"], result["sql"], result.get("warnings", [])
                        )
                        f.write(f"\n{view_sql}\n")
                        f.write("\n" + "-" * 60 + "\n")

            click.echo(f"✓ Generated {manifest['successful']} SQL views")
            click.echo(f"✓ Created manifest.json")
            click.echo(f"✓ Created all_views.sql")
        else:
            # Dry run - just create manifest in memory
            manifest = {
                "total_tables": len(results),
                "successful": sum(1 for r in results if r["success"]),
                "failed": sum(1 for r in results if not r["success"]),
                "by_confidence": {},
                "by_type": {},
                "tables": [],
            }

            for result in results:
                confidence = result.get("confidence", 0)
                level = (
                    "high"
                    if confidence >= 80
                    else "medium" if confidence >= 50 else "low"
                )

                if level not in manifest["by_confidence"]:
                    manifest["by_confidence"][level] = []
                manifest["by_confidence"][level].append(result["name"])

                table_type = result.get("type", "unknown")
                if table_type not in manifest["by_type"]:
                    manifest["by_type"][table_type] = []
                manifest["by_type"][table_type].append(result["name"])

            click.echo("\n[DRY RUN] No files written")

        # Print summary
        print_summary(manifest)

        # Show sample SQL if verbose
        if verbose and results:
            click.echo("\nSample SQL (first successful table):")
            for result in results:
                if result["success"]:
                    click.echo(f"\n{result['sql'][:500]}...")
                    break

        # Exit with appropriate code
        if manifest["failed"] > 0:
            sys.exit(1)  # Some failures
        else:
            sys.exit(0)  # Success

    except Exception as e:
        logger.error(f"Translation failed: {e}")
        click.echo(f"\n❌ Error: {e}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
