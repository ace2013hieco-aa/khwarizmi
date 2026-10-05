"""Root conftest for khwarizmi-research tests.

Pytest plugin isolation is handled via `addopts = "-p no:hypothesis -p no:anyio"`
in pyproject.toml, which disables the parent Hermes agent venv's plugins
before they load. This file exists for future shared fixtures.
"""
