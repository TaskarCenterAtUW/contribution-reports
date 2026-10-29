from contribution_reports import cli as quest_cli
from contribution_reports import paths, summary
from contribution_reports.osw import cli as osw_cli


def test_default_output_dir_follows_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert paths.default_output_dir() == tmp_path / "output"


def test_path_flags_default_to_none():
    assert quest_cli.parse_args([]).cache_file is None
    assert quest_cli.parse_args([]).output is None
    assert osw_cli.parse_args([]).cache_file is None
    assert osw_cli.parse_args([]).output is None
    assert summary.parse_args([]).cache_dir is None
    assert summary.parse_args([]).output is None
