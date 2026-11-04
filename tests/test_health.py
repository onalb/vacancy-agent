"""GET /api/health reports the package version."""

from vacancy_agent import __version__
from vacancy_agent.server import health


def test_health_reports_version():
    assert health() == {"ok": True, "version": __version__}
