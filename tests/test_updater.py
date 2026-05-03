"""Tests for agent/updater.py — pure semver comparison + flow plumbing."""

from agent.updater import _parse_semver


class TestParseSemver:
    def test_strips_v_prefix(self) -> None:
        assert _parse_semver("v1.10.0") == (1, 10, 0)
        assert _parse_semver("V2.0.0") == (2, 0, 0)

    def test_strips_prerelease_suffix(self) -> None:
        assert _parse_semver("1.10.0-beta.1") == (1, 10, 0)

    def test_two_part_version(self) -> None:
        assert _parse_semver("1.10") == (1, 10)

    def test_returns_empty_on_non_numeric(self) -> None:
        assert _parse_semver("unknown") == ()
        assert _parse_semver("1.foo.0") == ()

    def test_ordering_minor_vs_patch(self) -> None:
        assert _parse_semver("1.10.0") > _parse_semver("1.9.99")

    def test_ordering_v110_newer_than_v19(self) -> None:
        # The exact bug a naive string compare would miss.
        assert _parse_semver("v1.11.0") > _parse_semver("v1.9.1")
