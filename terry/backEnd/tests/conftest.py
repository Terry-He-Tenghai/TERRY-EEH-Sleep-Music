"""Platform capabilities shared by filesystem safety tests."""
import pytest


@pytest.fixture
def symlink_or_skip():
    def create(link, target):
        try:
            link.symlink_to(target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                pytest.skip('Windows symlink privilege unavailable; run with Developer Mode or on Linux')
            raise
    return create
