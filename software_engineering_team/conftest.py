"""
Pytest configuration and fixtures for software_engineering_team tests.

Run from software_engineering_team directory:
  cd software_engineering_team && pytest
"""

import sys
from pathlib import Path

# Add software_engineering_team to path so imports resolve
_team_dir = Path(__file__).resolve().parent
if str(_team_dir) not in sys.path:
    sys.path.insert(0, str(_team_dir))


def pytest_configure(config):
    """Configure logging so test runs show agent activity when -v or --log-cli-level is used."""
    import logging
    # Default: show INFO logs during tests when -v is passed
    if config.getoption("verbose", 0) > 0:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )
