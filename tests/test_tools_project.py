"""Tests for project tools."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from general_mini_agent.tools_project import (
    ToolRuntimeContext,
    create_edit_file,
    create_glob_files,
    create_list_files,
    create_project_tools,
    create_read_file,
    create_run_command,
    create_search_text,
    create_write_file,
    resolve_path,
)


def test_resolve_path_within_workspace() -> None:
    """Test resolve_path with paths within workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "file.txt").write_text("test")

        # Relative paths
        assert resolve_path(workspace, ".") == workspace.resolve()
        assert resolve_path(workspace, "file.txt") == (workspace / "file.txt").resolve()
        assert resolve_path(workspace, "subdir") == (workspace / "subdir").resolve()
        assert resolve_path(workspace, "subdir/file.txt") == (
            workspace / "subdir" / "file.txt"
        ).resolve()

        # With .. but still within workspace
        assert resolve_path(workspace, "subdir/..") == workspace.resolve()


def test_resolve_path_outside_workspace() -> None:
    """Test resolve_path with paths outside workspace raises error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Absolute path outside
        with pytest.raises(ValueError, match="path_outside_workspace"):
            resolve_path(workspace, "/etc/passwd")

        # .. escaping workspace
        with pytest.raises(ValueError, match="path_outside_workspace"):
            resolve_path(workspace, "../other")


class TestToolRuntimeContext:
    """Tests for ToolRuntimeContext."""

    def test_default_values(self) -> None:
        """Test default values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ToolRuntimeContext(workspace=Path(tmpdir))
            assert context.allow_read is True
            assert context.allow_write is False
            assert context.allow_execute is False
            assert context.max_file_size == 1_048_576
            assert context.max_search_results == 100
            assert context.command_timeout == 30.0
            assert context.max_command_output == 102_400

    def test_custom_values(self) -> None:
        """Test custom values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ToolRuntimeContext(
                workspace=Path(tmpdir),
                allow_read=False,
                allow_write=True,
                allow_execute=True,
                max_file_size=1024,
                max_search_results=50,
                command_timeout=60.0,
                max_command_output=204800,
            )
            assert context.allow_read is False
            assert context.allow_write is True
            assert context.allow_execute is True


class TestReadFile:
    """Tests for read_file tool."""

    def test_read_file_success(self) -> None:
        """Test reading a file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            read_file = create_read_file(context)

            (workspace / "test.txt").write_text("Hello, world!")

            result = read_file("test.txt")
            assert isinstance(result, dict)
            assert "error" not in result
            assert result["path"] == "test.txt"
            assert result["content"] == "Hello, world!"
            assert result["size"] == 13

    def test_read_file_not_found(self) -> None:
        """Test reading a file that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            read_file = create_read_file(context)

            result = read_file("missing.txt")
            assert isinstance(result, dict)
            assert result["error"] == "file_not_found"

    def test_read_file_outside_workspace(self) -> None:
        """Test reading a file outside workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            read_file = create_read_file(context)

            result = read_file("../outside.txt")
            assert isinstance(result, dict)
            assert result["error"] == "path_outside_workspace"

    def test_read_file_disabled(self) -> None:
        """Test read_file when read is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_read=False)
            read_file = create_read_file(context)

            result = read_file("test.txt")
            assert isinstance(result, dict)
            assert result["error"] == "read_disabled"

    def test_read_file_too_large(self) -> None:
        """Test reading a file larger than max_file_size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, max_file_size=10)
            read_file = create_read_file(context)

            (workspace / "large.txt").write_text("x" * 100)

            result = read_file("large.txt")
            assert isinstance(result, dict)
            assert result["error"] == "file_too_large"


class TestListFiles:
    """Tests for list_files tool."""

    def test_list_files_success(self) -> None:
        """Test listing files successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            list_files = create_list_files(context)

            (workspace / "file1.txt").write_text("test1")
            (workspace / "file2.py").write_text("test2")
            (workspace / "subdir").mkdir()

            result = list_files()
            assert isinstance(result, dict)
            assert "error" not in result
            entries = result["entries"]
            assert len(entries) == 3
            names = {e["name"] for e in entries}
            assert names == {"file1.txt", "file2.py", "subdir"}

    def test_list_files_with_pattern(self) -> None:
        """Test listing files with a pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            list_files = create_list_files(context)

            (workspace / "file1.txt").write_text("test1")
            (workspace / "file2.py").write_text("test2")

            result = list_files(pattern="*.txt")
            assert isinstance(result, dict)
            entries = result["entries"]
            assert len(entries) == 1
            assert entries[0]["name"] == "file1.txt"


class TestGlobFiles:
    """Tests for glob_files tool."""

    def test_glob_files_success(self) -> None:
        """Test globbing files successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            glob_files = create_glob_files(context)

            (workspace / "a.py").write_text("")
            (workspace / "b.py").write_text("")
            (workspace / "c.txt").write_text("")
            (workspace / "subdir").mkdir()
            (workspace / "subdir" / "d.py").write_text("")

            result = glob_files("**/*.py")
            assert isinstance(result, dict)
            assert "error" not in result
            matches = sorted(result["matches"])
            # Normalize for Windows
            matches = [m.replace("\\", "/") for m in matches]
            assert matches == ["a.py", "b.py", "subdir/d.py"]


class TestSearchText:
    """Tests for search_text tool."""

    def test_search_text_success(self) -> None:
        """Test searching text successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            search_text = create_search_text(context)

            (workspace / "test.txt").write_text("line 1\nhello line\nline 3\nhello again")

            result = search_text("hello")
            assert isinstance(result, dict)
            assert "error" not in result
            results = result["results"]
            assert len(results) == 2
            assert results[0]["line"] == 2
            assert "hello line" in results[0]["content"]
            assert results[1]["line"] == 4
            assert "hello again" in results[1]["content"]


class TestWriteFile:
    """Tests for write_file tool."""

    def test_write_file_success(self) -> None:
        """Test writing a file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            write_file = create_write_file(context)

            result = write_file("new.txt", "Hello from write!")
            assert isinstance(result, dict)
            assert "error" not in result
            assert result["path"] == "new.txt"

            assert (workspace / "new.txt").read_text() == "Hello from write!"

    def test_write_file_disabled(self) -> None:
        """Test write_file when write is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=False)
            write_file = create_write_file(context)

            result = write_file("test.txt", "content")
            assert isinstance(result, dict)
            assert result["error"] == "write_disabled"


class TestEditFile:
    """Tests for edit_file tool."""

    def test_edit_file_success(self) -> None:
        """Test editing a file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            edit_file = create_edit_file(context)

            (workspace / "test.txt").write_text("Hello, old text!")

            result = edit_file("test.txt", "old text", "new text")
            assert isinstance(result, dict)
            assert "error" not in result
            assert result["replacements"] == 1

            assert (workspace / "test.txt").read_text() == "Hello, new text!"

    def test_edit_file_no_match(self) -> None:
        """Test edit_file when no match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            edit_file = create_edit_file(context)

            (workspace / "test.txt").write_text("Hello, world!")

            result = edit_file("test.txt", "not there", "new")
            assert isinstance(result, dict)
            assert result["error"] == "no_match_found"

    def test_edit_file_multiple_matches(self) -> None:
        """Test edit_file when multiple matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            edit_file = create_edit_file(context)

            (workspace / "test.txt").write_text("foo foo foo")

            result = edit_file("test.txt", "foo", "bar")
            assert isinstance(result, dict)
            assert result["error"] == "multiple_matches"


class TestRunCommand:
    """Tests for run_command tool."""

    def test_run_command_success(self) -> None:
        """Test running a command successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_execute=True)
            run_command = create_run_command(context)

            # Run a simple command
            if os.name == "nt":
                result = run_command("cmd", args=["/c", "echo hello"])
            else:
                result = run_command("echo", args=["hello"])

            assert isinstance(result, dict)
            assert "error" not in result
            assert result["exit_code"] == 0
            # Check for any output
            assert isinstance(result["stdout"], str)

    def test_run_command_disabled(self) -> None:
        """Test run_command when execute is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_execute=False)
            run_command = create_run_command(context)

            result = run_command("echo", args=["hello"])
            assert isinstance(result, dict)
            assert result["error"] == "execute_disabled"


class TestCreateProjectTools:
    """Tests for create_project_tools factory."""

    def test_read_only(self) -> None:
        """Test create_project_tools with read only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace)
            tools = create_project_tools(context)

            assert len(tools) == 4
            names = {t.__name__ for t in tools}
            assert names == {"read_file", "list_files", "glob_files", "search_text"}

    def test_read_write(self) -> None:
        """Test create_project_tools with read and write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(workspace=workspace, allow_write=True)
            tools = create_project_tools(context)

            assert len(tools) == 6
            names = {t.__name__ for t in tools}
            assert "write_file" in names
            assert "edit_file" in names

    def test_all_capabilities(self) -> None:
        """Test create_project_tools with all capabilities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            context = ToolRuntimeContext(
                workspace=workspace,
                allow_write=True,
                allow_execute=True,
            )
            tools = create_project_tools(context)

            assert len(tools) == 7
            names = {t.__name__ for t in tools}
            assert "run_command" in names
