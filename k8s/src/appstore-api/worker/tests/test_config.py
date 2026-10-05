"""Tests for configuration."""

import os
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet


@pytest.mark.unit
class TestConfiguration:
    """Test configuration loading."""

    def test_settings_import(self):
        """Test that settings can be imported."""
        from appstore_worker.config import settings

        assert settings is not None

    def test_required_settings_exist(self):
        """Test that required settings attributes exist."""
        from appstore_worker.config import settings

        assert hasattr(settings, "DATABASE_URL")
        assert hasattr(settings, "WORKER_LEASE_SECONDS")
        assert hasattr(settings, "TEMP_REPO_BASE_PATH")
        assert hasattr(settings, "CREDENTIAL_ENCRYPTION_KEY")

    @patch.dict(
        os.environ,
        {
            "CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "DATABASE_URL": "postgresql://test@localhost/queue",
            "WORKER_CONCURRENCY": "7",
            "APPSTORE_API_URL": "http://api:8000",
        },
        clear=True,
    )
    def test_settings_from_environment(self):
        """Test loading settings from environment variables."""
        from importlib import reload

        from appstore_worker import config

        reload(config)

        assert config.settings.DATABASE_URL.endswith("/queue")
        assert config.settings.WORKER_CONCURRENCY == 7
