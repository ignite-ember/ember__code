"""Tests for IDE context tracker (session/ide_context.py)."""

import time

from ember_code.core.session.ide_context import IDEContext, OpenFile


class TestTrackFile:
    def test_track_single_file(self):
        ctx = IDEContext()
        ctx.track_file("/path/to/file.py")
        assert ctx.active_file == "/path/to/file.py"
        assert len(ctx.open_files) == 1

    def test_track_multiple_files(self):
        ctx = IDEContext()
        ctx.track_file("/a.py")
        ctx.track_file("/b.py")
        assert ctx.active_file == "/b.py"
        assert len(ctx.open_files) == 2

    def test_active_file_switches(self):
        ctx = IDEContext()
        ctx.track_file("/a.py")
        ctx.track_file("/b.py")
        ctx.track_file("/a.py")
        assert ctx.active_file == "/a.py"
        # b should no longer be active
        for f in ctx.open_files:
            if f.path == "/b.py":
                assert f.is_active is False

    def test_track_inactive(self):
        ctx = IDEContext()
        ctx.track_file("/a.py", active=True)
        ctx.track_file("/b.py", active=False)
        assert ctx.active_file == "/a.py"
        assert len(ctx.open_files) == 2

    def test_open_file_paths_most_recent_first(self):
        ctx = IDEContext()
        ctx.track_file("/old.py")
        time.sleep(0.01)
        ctx.track_file("/new.py")
        paths = ctx.open_file_paths
        assert paths[0] == "/new.py"
        assert paths[1] == "/old.py"

    def test_retrack_updates_timestamp(self):
        ctx = IDEContext()
        ctx.track_file("/a.py")
        first_time = ctx.open_files[0].opened_at
        time.sleep(0.01)
        ctx.track_file("/a.py")
        assert ctx.open_files[0].opened_at > first_time

    def test_evicts_old_files(self):
        ctx = IDEContext(max_files=3)
        ctx.track_file("/a.py")
        ctx.track_file("/b.py")
        ctx.track_file("/c.py")
        ctx.track_file("/d.py")
        assert len(ctx.open_files) <= 3
        # Active file should never be evicted
        assert ctx.active_file == "/d.py"

    def test_eviction_preserves_active(self):
        ctx = IDEContext(max_files=2)
        ctx.track_file("/a.py")  # oldest, but will be active
        ctx.track_file("/b.py")
        ctx.track_file("/c.py")
        ctx.track_file("/a.py")  # re-activate a
        ctx.track_file("/d.py")
        # a is active so should not be evicted
        paths = ctx.open_file_paths
        assert "/d.py" in paths


class TestParseSystemReminder:
    def test_detects_file_open_event(self):
        ctx = IDEContext()
        result = ctx.parse_system_reminder(
            "The user opened the file /src/main.py in the IDE. This may or may not be related."
        )
        assert result == "/src/main.py"
        assert ctx.active_file == "/src/main.py"

    def test_returns_none_for_unrelated(self):
        ctx = IDEContext()
        result = ctx.parse_system_reminder("Some random reminder text")
        assert result is None
        assert ctx.active_file is None

    def test_handles_complex_paths(self):
        ctx = IDEContext()
        result = ctx.parse_system_reminder(
            "The user opened the file /Users/foo/my-project/src/ember_code/tui/widgets/_dialogs.py in the IDE"
        )
        assert result == "/Users/foo/my-project/src/ember_code/tui/widgets/_dialogs.py"


class TestParseMessage:
    def test_extracts_from_system_reminder_tags(self):
        ctx = IDEContext()
        message = (
            "<system-reminder>\n"
            "The user opened the file /src/app.py in the IDE. "
            "This may or may not be related to the current task.\n"
            "</system-reminder>"
        )
        ctx.parse_message(message)
        assert ctx.active_file == "/src/app.py"

    def test_extracts_multiple_events(self):
        ctx = IDEContext()
        message = (
            "<system-reminder>The user opened the file /a.py in the IDE</system-reminder>"
            "Some user text here"
            "<system-reminder>The user opened the file /b.py in the IDE</system-reminder>"
        )
        ctx.parse_message(message)
        assert len(ctx.open_files) == 2
        assert ctx.active_file == "/b.py"

    def test_no_tags_is_noop(self):
        ctx = IDEContext()
        ctx.parse_message("Just a normal message with no tags")
        assert ctx.active_file is None
        assert len(ctx.open_files) == 0


class TestUpdateFromDiagnostics:
    def test_parses_file_uri(self):
        ctx = IDEContext()
        ctx.update_from_diagnostics(
            [
                {"uri": "file:///src/main.py", "diagnostics": []},
            ]
        )
        assert ctx.active_file == "/src/main.py"

    def test_first_entry_is_active(self):
        ctx = IDEContext()
        ctx.update_from_diagnostics(
            [
                {"uri": "file:///a.py", "diagnostics": []},
                {"uri": "file:///b.py", "diagnostics": []},
            ]
        )
        assert ctx.active_file == "/a.py"
        for f in ctx.open_files:
            if f.path == "/b.py":
                assert f.is_active is False

    def test_stores_diagnostics(self):
        ctx = IDEContext()
        diags = [{"severity": "error", "message": "Syntax error", "range": {"start": {"line": 10}}}]
        ctx.update_from_diagnostics(
            [
                {"uri": "file:///src/main.py", "diagnostics": diags},
            ]
        )
        tracked = ctx.open_files[0]
        assert len(tracked.diagnostics) == 1
        assert tracked.diagnostics[0]["message"] == "Syntax error"

    def test_handles_empty_response(self):
        ctx = IDEContext()
        ctx.update_from_diagnostics([])
        assert ctx.active_file is None

    def test_handles_missing_uri(self):
        ctx = IDEContext()
        ctx.update_from_diagnostics([{"diagnostics": []}])
        assert len(ctx.open_files) == 0


class TestDescribe:
    def test_empty_returns_empty_string(self):
        ctx = IDEContext()
        assert ctx.describe() == ""

    def test_shows_active_file(self):
        ctx = IDEContext()
        ctx.track_file("/src/main.py")
        desc = ctx.describe()
        assert "Active file" in desc
        assert "/src/main.py" in desc

    def test_shows_other_files(self):
        ctx = IDEContext()
        ctx.track_file("/a.py")
        ctx.track_file("/b.py")
        desc = ctx.describe()
        assert "Other open files" in desc
        assert "/a.py" in desc

    def test_shows_diagnostics(self):
        ctx = IDEContext()
        ctx.track_file("/src/main.py")
        ctx._files["/src/main.py"].diagnostics = [
            {
                "severity": "error",
                "message": "Undefined variable",
                "range": {"start": {"line": 42}},
            },
        ]
        desc = ctx.describe()
        assert "Diagnostics" in desc
        assert "L42" in desc
        assert "Undefined variable" in desc

    def test_limits_other_files_display(self):
        ctx = IDEContext()
        for i in range(15):
            ctx.track_file(f"/file{i}.py")
        desc = ctx.describe()
        # Should show at most 10 other files
        assert desc.count("`/file") <= 12  # 10 other + active + some formatting


class TestOpenFile:
    def test_defaults(self):
        f = OpenFile(path="/test.py")
        assert f.is_active is False
        assert f.diagnostics == []
        assert f.opened_at > 0
