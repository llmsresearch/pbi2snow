# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2024-09-10

### Added
- Complete Power BI to Snowflake SQL translation engine
- M Language expression translator with enhanced pattern recognition
- DAX formula converter for Snowflake SQL equivalents
- Unified CLI with multiple translation modes (basic, enhanced, aggressive)
- Configuration-driven translation with confidence thresholds
- Comprehensive relationship mapping and foreign key preservation
- Optimized Snowflake view generation with proper naming conventions
- Production-ready error handling and detailed logging
- Support for calculated columns, tables, and measures
- Multiple output formats (individual views, combined SQL, manifest)

### Features
- Python 3.8+ compatibility
- Command-line interface with comprehensive options
- Python API for programmatic usage
- Multiple translation modes for different use cases
- Confidence scoring for translation quality assessment
- Table filtering and exclusion capabilities
- Dry-run mode for preview without file creation

### Technical
- Modular architecture with separate extract, translate, and generate components
- Comprehensive test coverage across Python versions
- CI/CD pipeline with automated PyPI publishing
- Type hints and static analysis support
- Black code formatting and flake8 linting
- MIT license for open source usage

### Documentation
- Comprehensive README with usage examples
- Installation instructions for PyPI and source
- API documentation with code examples
- Command-line reference with all options
- Roadmap for future enhancements