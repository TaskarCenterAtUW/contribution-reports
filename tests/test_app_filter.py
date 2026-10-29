
from contribution_reports import cli
from contribution_reports.constants import APP_CREATED_BY_PREFIXES
from contribution_reports.events import find_event_window
from contribution_reports.render import filter_app_changesets


def _cs(created_by):
    return {"id": 1, "tags": {"created_by": created_by}}


def test_default_filter_filters_by_constant():
    assert filter_app_changesets([_cs("GIG 3.2"), _cs("Rapid 2")]) == [_cs("GIG 3.2")]


def test_empty_tuple_returns_all_items():
    items = [_cs("Rapid 2"), _cs("anything")]
    assert filter_app_changesets(items, ()) == items


def test_filter_app_changesets_with_custom_prefixes():
    items = [_cs("MyApp 1"), _cs("GIG 1")]
    assert filter_app_changesets(items, ("MyApp",)) == [_cs("MyApp 1")]


def test_resolve_app_filter_precedence():
    class A:
        app_filter = None
        no_app_filter = False
    a = A()
    assert cli.resolve_app_filter(a, {}) == APP_CREATED_BY_PREFIXES
    assert cli.resolve_app_filter(a, {"WS_APP_FILTER": "Foo, Bar"}) == ("Foo", "Bar")
    a.app_filter = ("Baz", "Qux")
    assert cli.resolve_app_filter(a, {"WS_APP_FILTER": "Foo"}) == ("Baz", "Qux")
    a.app_filter = None
    a.no_app_filter = True
    assert cli.resolve_app_filter(a, {"WS_APP_FILTER": "Foo"}) == ()


def test_resolve_app_filter_uses_builtin_when_all_segments_are_empty():
    class A:
        app_filter = None
        no_app_filter = False
    assert cli.resolve_app_filter(A(), {"WS_APP_FILTER": ",,,"}) == APP_CREATED_BY_PREFIXES
    assert cli.resolve_app_filter(A(), {"WS_APP_FILTER": " , , "}) == APP_CREATED_BY_PREFIXES


def test_window_seed_depends_on_filter():
    def cs_day(when, by):
        return {"tags": {"created_by": by}, "created_at": when}
    items = [cs_day("2026-01-01T10:00:00Z", "Rider"), cs_day("2026-01-01T10:01:00Z", "Rider")]
    assert find_event_window(items) is None  # no app changesets
    assert find_event_window(items, ()) is not None  # seeded with all
