from pathlib import Path

import pytest

from workspace_session_manager.config import AppConfig, load_config
from workspace_session_manager.errors import ConfigurationError
from workspace_session_manager.paths import AppPaths


def test_defaults_use_isolated_namespace_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WS_DEV_ROOT", str(tmp_path))
    paths = AppPaths.discover()
    config = load_config(paths)
    assert paths.state_dir == tmp_path / "state"
    assert config.schema_version == 1
    assert not paths.state_dir.exists()


def test_config_is_strict_toml(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    paths.config_dir.mkdir()
    paths.config_file.write_text("unknown = true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown"):
        load_config(paths)


def test_tilde_paths_expand() -> None:
    config = AppConfig(legacy_state_dirs=(Path("~/.legacy-wf"),))
    assert config.legacy_state_dirs[0].is_absolute()


def test_motion_configuration_is_strict() -> None:
    config = AppConfig.model_validate({"interface": {"animations": "full", "reduce_motion": True}})
    assert config.interface.animations == "full"
    assert config.interface.reduce_motion
    with pytest.raises(ValueError):
        AppConfig.model_validate({"interface": {"animations": "constant"}})


def test_attention_scan_budget_is_bounded() -> None:
    assert AppConfig().attention_scan_budget == 8
    assert AppConfig(attention_scan_budget=1).attention_scan_budget == 1
    assert AppConfig(attention_scan_budget=64).attention_scan_budget == 64
    with pytest.raises(ValueError):
        AppConfig(attention_scan_budget=0)
    with pytest.raises(ValueError):
        AppConfig(attention_scan_budget=65)
