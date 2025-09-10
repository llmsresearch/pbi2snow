# PBI2Snow

[![PyPI version](https://badge.fury.io/py/pbi2snow.svg)](https://badge.fury.io/py/pbi2snow)
[![Python](https://img.shields.io/pypi/pyversions/pbi2snow.svg)](https://pypi.org/project/pbi2snow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Power BI to Snowflake SQL Translator** - Convert Power BI models (.bim files) to Snowflake SQL with enhanced M and DAX support.

## Features

- **Complete Model Translation**: Extract and convert entire Power BI data models
- **M Language Support**: Advanced translation of Power Query M expressions to SQL
- **DAX Translation**: Convert DAX formulas to Snowflake SQL equivalents
- **Relationship Mapping**: Preserve table relationships and foreign keys
- **View Generation**: Create optimized Snowflake views with proper naming conventions
- **Configuration Options**: Flexible translation modes and confidence levels
- **Production Ready**: Comprehensive error handling and logging

## Installation

### From PyPI (Recommended)

```bash
pip install pbi2snow
```

### From Source

```bash
git clone https://github.com/llmsresearch/pbi2snow.git
cd pbi2snow
pip install -e .
```

## Quick Start

### Command Line Usage

```bash
# Basic usage
pbi2snow --bim-file model.bim --output-dir output/

# With custom schema and verbose output
pbi2snow --bim-file model.bim --output-dir output/ --target-schema MY_SCHEMA --verbose

# Production mode with high confidence threshold
pbi2snow --bim-file model.bim --mode production --confidence-threshold 80
```

### Python API

```python
from pbi2snow import extract
from pbi2snow.translator import UnifiedTranslator, TranslationConfig

# Load Power BI model
model_data = extract.collect('path/to/model.bim')

# Configure translator
config = TranslationConfig(
    target_schema='SEMANTIC',
    confidence_threshold=70,
    mode='production'
)

# Translate model
translator = UnifiedTranslator(config)
results = []

for table in model_data['tables']:
    result = translator.translate_table(table)
    results.append(result)

print(f"Translated {len(results)} tables")
```

## Command Line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--bim-file` | `-b` | `input/Model.bim` | Path to the BIM file |
| `--output-dir` | `-o` | `out_unified` | Output directory for SQL files |
| `--target-schema` | `-s` | `SEMANTIC` | Target Snowflake schema name |
| `--mode` | `-m` | `balanced` | Translation mode: `conservative`, `balanced`, `aggressive` |
| `--confidence-threshold` | `-c` | `50` | Minimum confidence level (0-100) |
| `--verbose` | `-v` | `False` | Enable verbose logging |

## Translation Modes

### Conservative Mode
- High accuracy, lower coverage
- Only translates well-understood patterns
- Confidence threshold: 80+

### Balanced Mode (Default)
- Good balance of accuracy and coverage
- Handles most common scenarios
- Confidence threshold: 50+

### Aggressive Mode
- Maximum coverage, experimental translations
- May require manual review
- Confidence threshold: 20+

## Output Structure

```
output/
├── views/                  # Generated Snowflake views
│   ├── V_TABLE_NAME.sql   # Individual view files
│   └── ...
├── manifest.json          # Translation summary and metadata
└── all_views.sql          # Combined SQL file
```

## Supported Power BI Features

### M Language (Power Query)
- Table transformations
- Column operations
- Filtering and grouping
- Joins and merges
- Data type conversions
- Custom functions (limited)

### DAX Expressions
- Basic calculations
- Aggregations (SUM, COUNT, AVG, etc.)
- Time intelligence functions
- Filter functions (FILTER, CALCULATE)
- Relationship functions
- Complex nested expressions (limited)

### Model Elements
- Tables and columns
- Relationships and foreign keys
- Calculated columns
- Calculated tables
- Measures (basic)

## Use Cases

- **Data Warehouse Migration**: Move Power BI models to Snowflake
- **SQL Modernization**: Convert legacy BI logic to modern SQL
- **Multi-Platform Support**: Run the same logic on different platforms
- **Performance Optimization**: Leverage Snowflake's compute power
- **Compliance & Governance**: Centralize data transformations


### Development Setup

```bash
# Clone the repository
git clone https://github.com/llmsresearch/pbi2snow.git
cd pbi2snow

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black pbi2snow/
flake8 pbi2snow/
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Roadmap

- [ ] Enhanced DAX function support
- [ ] Azure Synapse SQL support
- [ ] Power BI Premium integration
- [ ] Real-time translation validation
- [ ] Visual Studio Code extension
- [ ] Automated testing framework