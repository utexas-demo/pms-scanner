"""Unit tests for the multi-env config rewrite — T007 (004 foundational).

Source of truth: specs/004-multi-env-uploads/contracts/config-schema.md and
data-model.md. Covers required-field absence, same-watch-folder rejection
(FR-009), same-offset rejection (FR-006c), unknown-env rejection, derived
in_progress_dir/processed_dir, and the 003-era flat-var migration warning.
"""
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from config import AppSettings, ConfigError, Environment, load_settings
from machine import MachineIdentity


@contextmanager
def _patched_env(mapping: dict[str, str]):
    with patch.dict(os.environ, mapping, clear=True):
        yield


def _build(mapping: dict[str, str]) -> AppSettings:
    with _patched_env(mapping):
        return load_settings(dotenv=False)


def _base_env(prod_dir: str, staging_dir: str) -> dict[str, str]:
    return {
        "MACHINE_IDENTITY": "macmini",
        "NTP__SOURCE": "pool.ntp.org",
        "NTP__STARTUP_REQUIRED": "false",
        "ENVIRONMENTS": "production,staging",
        "ENV_PRODUCTION__WATCH_DIR": prod_dir,
        "ENV_PRODUCTION__API_TOKEN": "prod-token",
        "ENV_PRODUCTION__SCHEDULE_OFFSET_SECONDS": "0",
        "ENV_STAGING__WATCH_DIR": staging_dir,
        "ENV_STAGING__API_TOKEN": "staging-token",
        "ENV_STAGING__SCHEDULE_OFFSET_SECONDS": "15",
    }


def test_happy_path_two_envs(tmp_path: Path) -> None:
    s = _build(_base_env(str(tmp_path / "p"), str(tmp_path / "s")))
    assert s.machine == MachineIdentity("macmini")
    by_name = {e.name: e for e in s.environments}
    assert set(by_name) == {"production", "staging"}
    assert str(by_name["production"].backend_base_url) == "https://adg.mpsinc.io"
    assert str(by_name["staging"].backend_base_url) == "https://dev.adg.mpsinc.io"
    assert by_name["production"].schedule_offset_seconds == 0
    assert by_name["staging"].schedule_offset_seconds == 15


def test_missing_machine_identity_rejected(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    del env["MACHINE_IDENTITY"]
    with pytest.raises(ConfigError, match="MACHINE_IDENTITY"):
        _build(env)


def test_missing_env_block_rejected(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    del env["ENV_PRODUCTION__WATCH_DIR"]
    del env["ENV_PRODUCTION__API_TOKEN"]
    del env["ENV_PRODUCTION__SCHEDULE_OFFSET_SECONDS"]
    with pytest.raises(ConfigError, match="(?i)production"):
        _build(env)


def test_empty_api_token_rejected(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["ENV_STAGING__API_TOKEN"] = "   "
    with pytest.raises(ConfigError, match="(?i)staging"):
        _build(env)


def test_offset_out_of_range_rejected(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["ENV_STAGING__SCHEDULE_OFFSET_SECONDS"] = "60"
    with pytest.raises(ConfigError, match="(?i)offset|staging"):
        _build(env)


def test_same_watch_folder_rejected_naming_both(tmp_path: Path) -> None:
    same = str(tmp_path / "shared")
    with pytest.raises(ConfigError) as exc:
        _build(_base_env(same, same))
    msg = str(exc.value).lower()
    assert "production" in msg and "staging" in msg


def test_same_offset_rejected_naming_both(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["ENV_STAGING__SCHEDULE_OFFSET_SECONDS"] = "0"  # collides with production :00
    with pytest.raises(ConfigError) as exc:
        _build(env)
    msg = str(exc.value).lower()
    assert "production" in msg and "staging" in msg


def test_unknown_env_name_rejected(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["ENVIRONMENTS"] = "production,qa"
    with pytest.raises(ConfigError, match="(?i)qa"):
        _build(env)


def test_disabled_env_excluded_and_skips_distinctness(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["ENV_STAGING__ENABLED"] = "false"
    env["ENV_STAGING__SCHEDULE_OFFSET_SECONDS"] = "0"  # would collide if enabled
    s = _build(env)
    names = {e.name for e in s.environments if e.enabled}
    assert names == {"production"}


def test_environment_path_derivations(tmp_path: Path) -> None:
    s = _build(_base_env(str(tmp_path / "p"), str(tmp_path / "s")))
    prod = next(e for e in s.environments if e.name == "production")
    machine = s.machine
    assert prod.processed_dir == tmp_path / "p" / "processed"
    assert prod.in_progress_dir(machine) == tmp_path / "p" / "in-progress" / "macmini"
    assert machine.in_progress_dir(prod) == prod.in_progress_dir(machine)


def test_api_token_is_secret_not_in_repr(tmp_path: Path) -> None:
    s = _build(_base_env(str(tmp_path / "p"), str(tmp_path / "s")))
    prod = next(e for e in s.environments if e.name == "production")
    assert "prod-token" not in repr(prod)
    assert "prod-token" not in str(prod)
    assert prod.api_token.get_secret_value() == "prod-token"


def test_flat_003_vars_without_environments_are_rejected(
    tmp_path: Path,
) -> None:
    """The 003 flat-var migration shim is gone (T057): no ENVIRONMENTS → error."""
    legacy = {
        "MACHINE_IDENTITY": "macmini",
        "NTP__STARTUP_REQUIRED": "false",
        "WATCH_DIR": str(tmp_path / "legacy"),
        "BACKEND_BASE_URL": "https://adg.mpsinc.io",
        "API_TOKEN": "legacy-token",
    }
    with pytest.raises(ConfigError, match="(?i)ENVIRONMENTS"):
        _build(legacy)


def test_environments_present_ignores_legacy_flat_vars(tmp_path: Path) -> None:
    env = _base_env(str(tmp_path / "p"), str(tmp_path / "s"))
    env["WATCH_DIR"] = "/should/be/ignored"
    s = _build(env)
    watch_dirs = {str(e.watch_dir) for e in s.environments}
    assert "/should/be/ignored" not in watch_dirs


def test_environment_is_a_dataclass_or_model_with_required_fields(
    tmp_path: Path,
) -> None:
    s = _build(_base_env(str(tmp_path / "p"), str(tmp_path / "s")))
    e = s.environments[0]
    assert isinstance(e, Environment)
    assert e.name in {"production", "staging"}
    assert isinstance(e.watch_dir, Path)
