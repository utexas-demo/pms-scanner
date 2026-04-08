# pms-scanner Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-08

## Active Technologies

- Python 3.12 (from `Dockerfile`) + watchdog ≥4.0, requests ≥2.31, pydantic-settings ≥2.2, python-dotenv ≥1.0, tenacity ≥8.0 (new) (001-folder-monitor-upload)

## Project Structure

```text
scanner/          # Source package (config.py, watcher.py, __main__.py)
tests/
  unit/
  integration/
  contract/
pyproject.toml    # ruff, mypy, pytest, coverage config
requirements.txt
requirements-dev.txt
README.md
```

## Commands

pytest; ruff check .; mypy --strict scanner/

## Code Style

Python 3.12 (from `Dockerfile`): Follow standard conventions

## Recent Changes

- 001-folder-monitor-upload: Added Python 3.12 (from `Dockerfile`) + watchdog ≥4.0, requests ≥2.31, pydantic-settings ≥2.2, python-dotenv ≥1.0, tenacity ≥8.0 (new)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
