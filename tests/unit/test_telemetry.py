import json

import pytest

from browser_harness import telemetry


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("BH_CONFIG_DIR", str(tmp_path))
    for name in telemetry.TELEMETRY_ENVS:
        monkeypatch.delenv(name, raising=False)
    sent = []
    monkeypatch.setattr(telemetry, "_send_detached", sent.append)
    return tmp_path, sent


def test_off_by_default_and_sends_nothing(isolated):
    config_dir, sent = isolated
    assert telemetry.is_enabled() is False
    telemetry.capture("event")
    telemetry.capture_cli_event(action="run", command="run", task="secret task")
    assert sent == []
    status = telemetry.status()
    assert status["enabled"] is False
    assert status["opt_in"] is True
    # No install id is minted while telemetry is off.
    assert status["install_id"] is None
    assert not (config_dir / "telemetry.json").exists()


def test_upstream_opt_out_config_stays_off(isolated):
    config_dir, sent = isolated
    (config_dir / "telemetry.json").write_text(json.dumps({"install_id": "0" * 32}))
    assert telemetry.is_enabled() is False
    telemetry.capture("event")
    assert sent == []


def test_enable_command_opts_in_and_disable_opts_out(isolated):
    _, sent = isolated
    assert telemetry.run_telemetry_cli(["enable"]) == 0
    assert telemetry.is_enabled() is True
    telemetry.capture("event")
    assert len(sent) == 1
    assert telemetry.run_telemetry_cli(["disable"]) == 0
    assert telemetry.is_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_truthy_env_opts_in(isolated, monkeypatch, value):
    monkeypatch.setenv("BH_TELEMETRY", value)
    assert telemetry.is_enabled() is True
    assert telemetry.status()["enabled_by_env"] is True


def test_falsy_env_beats_config_and_other_envs(isolated, monkeypatch):
    telemetry.set_enabled(True)
    monkeypatch.setenv("BROWSER_HARNESS_TELEMETRY", "1")
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "false")
    assert telemetry.is_enabled() is False
    assert telemetry.status()["disabled_by_env"] is True
