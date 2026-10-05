"""Tests for hermes package — import + version sanity (Phase 0)."""
import hermes


def test_version():
    assert hermes.__version__ == "0.1.0"


def test_subpackages_importable():
    import hermes.core  # noqa
    import hermes.research
    import hermes.agents
    import hermes.tools
    import hermes.persistence
    import hermes.artifacts
    import hermes.recovery
    import hermes.engineering
    import hermes.vault
    import hermes.security  # noqa
