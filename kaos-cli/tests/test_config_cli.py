import yaml
from typer.testing import CliRunner

from kaos_cli.config import load_config, save_config
from kaos_cli.main import app


runner = CliRunner()


def test_local_config_precedes_home_config(tmp_path):
    cwd = tmp_path / "work"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    (home / ".kaos-config.yaml").write_text("namespace: home\n")
    (cwd / ".kaos-config.yaml").write_text("namespace: local\n")

    assert load_config(cwd=cwd, home=home)["namespace"] == "local"


def test_config_roundtrip(tmp_path):
    path = tmp_path / ".kaos-config.yaml"
    config = load_config(path)
    config["gateway"]["through_gateway"] = True
    config["sessions"]["alice"] = {"token": "token"}
    save_config(config, path)

    assert load_config(path) == config
    assert yaml.safe_load(path.read_text())["gateway"]["through_gateway"] is True


def test_config_set_and_get(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "gateway.through_gateway", "true"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["config", "get", "gateway.through_gateway"])
    assert result.exit_code == 0
    assert result.output.strip() == "true"
