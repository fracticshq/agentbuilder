"""
Tests for _preload_akv_secrets boot-strap logic in app/config.py.

These tests should FAIL before Fix 1 is applied (config.py does not call
_load_dotenv_early so USE_AZURE_KEYVAULT from .env is never seen).
"""
import os
from unittest.mock import patch


def test_preload_reads_env_file_before_checking_akv(tmp_path, monkeypatch):
    """_preload_akv_secrets must parse .env for USE_AZURE_KEYVAULT before deciding
    whether to call AKV — this fails currently because the flag is never loaded."""
    env_file = tmp_path / ".env"
    env_file.write_text("USE_AZURE_KEYVAULT=true\nAZURE_KEYVAULT_NAME=fake-vault\n")

    # Ensure the env vars are NOT already in the process environment
    monkeypatch.delenv("USE_AZURE_KEYVAULT", raising=False)
    monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)

    with patch("app.config.fetch_akv_secrets") as mock_akv:
        mock_akv.return_value = {"OPENAI_API_KEY": "sk-test"}
        from app.config import _preload_akv_secrets
        _preload_akv_secrets(env_path=str(env_file))

    # After fix: fetch_akv_secrets must have been called once
    mock_akv.assert_called_once()


def test_preload_does_not_override_existing_env_vars(tmp_path, monkeypatch):
    """Secrets already in the environment must not be overwritten by AKV values."""
    env_file = tmp_path / ".env"
    env_file.write_text("USE_AZURE_KEYVAULT=true\nAZURE_KEYVAULT_NAME=fake-vault\n")

    monkeypatch.delenv("USE_AZURE_KEYVAULT", raising=False)
    monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-already-set")

    with patch("app.config.fetch_akv_secrets") as mock_akv:
        mock_akv.return_value = {"OPENAI_API_KEY": "sk-from-akv"}
        from app.config import _preload_akv_secrets
        _preload_akv_secrets(env_path=str(env_file))

    # The pre-existing value must survive
    assert os.environ["OPENAI_API_KEY"] == "sk-already-set"


def test_preload_skips_akv_when_flag_false(tmp_path, monkeypatch):
    """When USE_AZURE_KEYVAULT=false, fetch_akv_secrets must not be called."""
    env_file = tmp_path / ".env"
    env_file.write_text("USE_AZURE_KEYVAULT=false\n")

    monkeypatch.delenv("USE_AZURE_KEYVAULT", raising=False)

    with patch("app.config.fetch_akv_secrets") as mock_akv:
        from app.config import _preload_akv_secrets
        _preload_akv_secrets(env_path=str(env_file))

    mock_akv.assert_not_called()
