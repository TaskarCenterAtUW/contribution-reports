import pytest

from contribution_reports import env


def test_missing_environment_file_does_not_cause_exit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WS_ENV_FILE", raising=False)
    monkeypatch.setenv("WS_TORCH", "from-shell")
    result = env.load_env()
    assert result.get("WS_TORCH") == "from-shell"  # no SystemExit


def test_env_file_walkup_from_cwd(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    root_env.write_text("WS_DEEP=dotted-value\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    monkeypatch.delenv("WS_ENV_FILE", raising=False)
    assert env.load_env().get("WS_DEEP") == "dotted-value"


def test_ws_env_file_environment_variable_selects_file(tmp_path, monkeypatch):
    f = tmp_path / "other.env"
    f.write_text("WS_SELECTED=yes\n")
    monkeypatch.setenv("WS_ENV_FILE", str(f))
    assert env.load_env().get("WS_SELECTED") == "yes"


def test_missing_ws_env_file_causes_system_exit(monkeypatch):
    monkeypatch.setenv("WS_ENV_FILE", "/nonexistent/nope.env")
    with pytest.raises(SystemExit):
        env.load_env()


def test_explicitly_passed_missing_env_file_exits(tmp_path):
    with pytest.raises(SystemExit):
        env.load_env(tmp_path / "nope.env")


def test_load_env_supports_file_paths_with_spaces(tmp_path, monkeypatch):
    monkeypatch.delenv("WS_ENV_FILE", raising=False)
    f = tmp_path / "my settings.env"
    f.write_text("WS_SPACED=yes\n")
    assert env.load_env(f).get("WS_SPACED") == "yes"


def test_unterminated_quote_in_env_file_causes_system_exit(tmp_path):
    f = tmp_path / ".env"
    f.write_text("WS_BROKEN='unterminated quote\n")
    with pytest.raises(SystemExit):
        env.load_env(f)


def test_shell_beats_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("WS_OVERLAP=fromfile\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WS_ENV_FILE", raising=False)
    monkeypatch.setenv("WS_OVERLAP", "fromshell")
    assert env.load_env().get("WS_OVERLAP") == "fromshell"
