# Release Guide

## Automated PyPI Publishing

This project uses GitHub Actions for automated PyPI publishing. The CI/CD pipeline is triggered on version tags.

### Release Process

1. **Update Version**
   ```bash
   # Edit pyproject.toml to update version
   version = "2.1.0"  # Update this line
   ```

2. **Update Changelog**
   ```bash
   # Edit CHANGELOG.md to add new version section
   ## [2.1.0] - YYYY-MM-DD
   ### Added
   - New feature descriptions
   ### Changed  
   - Changed feature descriptions
   ### Fixed
   - Bug fix descriptions
   ```

3. **Commit Changes**
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "Bump version to 2.1.0"
   git push origin main
   ```

4. **Create and Push Tag**
   ```bash
   git tag v2.1.0
   git push origin v2.1.0
   ```

5. **Monitor Pipeline**
   ```bash
   gh run list --limit 3
   gh run view [RUN_ID] --log
   ```

### Pipeline Stages

1. **Test** - Runs tests across Python 3.8-3.12
2. **Build** - Creates distribution packages
3. **Publish** - Uploads to PyPI (only on tags)

### Manual Publishing (if needed)

```bash
# Build the package
python -m build

# Upload to PyPI
twine upload dist/*
```

### Environment Setup

The following secrets are configured in GitHub:
- `PYPI_API_TOKEN` - PyPI API token for publishing

### Monitoring

- GitHub Actions: https://github.com/llmsresearch/pbi2snow/actions
- PyPI Package: https://pypi.org/project/pbi2snow/
- Release History: https://github.com/llmsresearch/pbi2snow/releases