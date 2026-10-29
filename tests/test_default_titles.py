import inspect

from contribution_reports import render, summary
from contribution_reports.summary import parse_args


def test_default_report_title_equals_contribution_report():
    assert render.DEFAULT_REPORT_TITLE == "Contribution Report"


def test_default_summary_title_is_contribution_summary():
    assert summary.DEFAULT_SUMMARY_TITLE == "Contribution Summary"
    assert parse_args([]).report_title == "Contribution Summary"


def test_render_uses_default_report_title_constant():
    assert "DEFAULT_REPORT_TITLE" in inspect.getsource(render.render_report)
