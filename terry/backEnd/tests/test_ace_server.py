"""Test ACE server provisioning module."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import ace_server_manager
from ace_server_manager import ServerConfig
from app import app

client = TestClient(app)


def test_server_config_validation():
    """Valid configs pass validation."""
    config = ServerConfig(
        host="example.com",
        port=22,
        username="user",
        password="secret123",
        remote_port=8001,
        local_port=8001
    )
    assert config.host == "example.com"
    assert config.password.get_secret_value() == "secret123"


def test_server_config_rejects_invalid_host():
    """Invalid hostnames are rejected."""
    with pytest.raises(ValueError):
        ServerConfig(
            host="invalid host with spaces",
            port=22,
            username="user",
            password="secret"
        )


def test_server_config_rejects_invalid_ports():
    """Port numbers must be in valid range."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ServerConfig(host="example.com", port=0, username="user", password="secret")
    with pytest.raises(ValidationError):
        ServerConfig(host="example.com", port=99999, username="user", password="secret")


def test_status_endpoint_when_dependencies_missing():
    """Status endpoint returns error when dependencies unavailable."""
    with patch.object(ace_server_manager, 'DEPENDENCIES_AVAILABLE', False):
        response = client.get("/api/ace-server/status")
        assert response.status_code == 200
        data = response.json()
        assert data["stage"] == "error"
        assert "paramiko" in data["message"]


def test_start_endpoint_rejects_without_dependencies():
    """Start endpoint returns 503 when dependencies missing."""
    with patch.object(ace_server_manager, 'DEPENDENCIES_AVAILABLE', False):
        response = client.post("/api/ace-server/start", json={
            "host": "example.com",
            "port": 22,
            "username": "user",
            "password": "secret"
        })
        assert response.status_code == 503
        assert "paramiko" in response.json()["detail"]


def test_manager_tracks_job_status(monkeypatch):
    """Manager maintains job status across lifecycle."""
    if not ace_server_manager.DEPENDENCIES_AVAILABLE:
        pytest.skip("paramiko/psutil not available")
    
    manager = ace_server_manager.ServerManager()
    assert manager.get_status()["stage"] == "idle"
    
    # Simulate failed connection
    def mock_provision(self, job_id, config):
        self._update_stage("error", "连接失败")
    
    monkeypatch.setattr(ace_server_manager.ServerManager, "_provision", mock_provision)
    
    config = ServerConfig(
        host="invalid.example.com",
        port=22,
        username="user",
        password="test123"
    )
    manager.start(config)
    import time
    time.sleep(0.2)  # Let worker thread run
    
    status = manager.get_status()
    assert status["stage"] == "error"
    assert "连接失败" in status["message"]


def test_password_not_logged_in_status():
    """Password is not exposed in status or logs."""
    if not ace_server_manager.DEPENDENCIES_AVAILABLE:
        pytest.skip("paramiko/psutil not available")
    
    manager = ace_server_manager.ServerManager()
    config = ServerConfig(
        host="example.com",
        port=22,
        username="testuser",
        password="SuperSecret123!"
    )
    
    # Even if start fails immediately, password should not appear
    try:
        manager.start(config)
    except Exception:
        pass
    
    status = manager.get_status()
    log_text = " ".join(status["log"])
    assert "SuperSecret123!" not in log_text
    assert "SuperSecret123!" not in status["message"]
