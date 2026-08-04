"""Project tools for file operations and command execution.

These tools are not automatically registered with any Agent. Use
`create_project_tools(context)` to get a list of tools for your Agent.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .tools import JSONValue, Tool, tool


@dataclass(frozen=True)
class ToolRuntimeContext:
    """Runtime context for project tools."""

    # Workspace path: tools can only access files under this path
    workspace: Path
    # Allow read operations (default: True)
    allow_read: bool = True
    # Allow write operations (default: False)
    allow_write: bool = False
    # Allow command execution (default: False)
    allow_execute: bool = False
    # Maximum file size to read (default: 1MB)
    max_file_size: int = 1_048_576
    # Maximum search results (default: 100)
    max_search_results: int = 100
    # Command timeout in seconds (default: 30)
    command_timeout: float = 30.0
    # Maximum command output bytes (default: 100KB)
    max_command_output: int = 102_400


def resolve_path(workspace: Path, path: str) -> Path:
    """Resolve a path relative to workspace, ensuring it stays within workspace.

    Args:
        workspace: The workspace root path
        path: The path to resolve

    Returns:
        The resolved absolute path

    Raises:
        ValueError: If the path is outside the workspace
    """
    workspace_abs = workspace.resolve()
    resolved = (workspace_abs / path).resolve()

    # Check if resolved path is within workspace
    if workspace_abs not in resolved.parents and resolved != workspace_abs:
        raise ValueError("path_outside_workspace")

    return resolved


def _error_result(error_code: str, message: str) -> JSONValue:
    """Create an error result dictionary."""
    return {"error": error_code, "message": message}


def create_read_file(context: ToolRuntimeContext) -> Tool:
    """Create a read_file tool for the given context."""

    @tool(description="Read a file's content")
    def read_file(path: str, encoding: str = "utf-8") -> JSONValue:
        """Read a file's content.

        Args:
            path: Path to the file, relative to workspace
            encoding: File encoding (default: utf-8)

        Returns:
            File content or error dictionary
        """
        if not context.allow_read:
            return _error_result("read_disabled", "Read operations are disabled")

        try:
            file_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        if not file_path.exists():
            return _error_result("file_not_found", f"File not found: {path}")

        if not file_path.is_file():
            return _error_result("file_not_found", f"Not a file: {path}")

        file_size = file_path.stat().st_size
        if file_size > context.max_file_size:
            return _error_result(
                "file_too_large",
                f"File {path} is {file_size} bytes, "
                f"max allowed is {context.max_file_size}",
            )

        try:
            content = file_path.read_text(encoding=encoding)
            return {"path": path, "content": content, "size": file_size}
        except UnicodeDecodeError:
            return _error_result(
                "encoding_error",
                f"Failed to decode {path} with encoding {encoding}",
            )
        except Exception as e:
            return _error_result("read_failed", f"Failed to read {path}: {e}")

    return read_file


def create_list_files(context: ToolRuntimeContext) -> Tool:
    """Create a list_files tool for the given context."""

    @tool(description="List files and directories in a path")
    def list_files(path: str = ".", pattern: str | None = None) -> JSONValue:
        """List files and directories in a path.

        Args:
            path: Directory path, relative to workspace (default: ".")
            pattern: Optional glob pattern to filter files

        Returns:
            List of file/directory info or error dictionary
        """
        if not context.allow_read:
            return _error_result("read_disabled", "Read operations are disabled")

        try:
            dir_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        if not dir_path.exists():
            return _error_result("dir_not_found", f"Directory not found: {path}")

        if not dir_path.is_dir():
            return _error_result("dir_not_found", f"Not a directory: {path}")

        try:
            result: list[dict[str, Any]] = []
            for item in sorted(dir_path.iterdir()):
                if pattern and not item.match(pattern):
                    continue
                item_type = "dir" if item.is_dir() else "file"
                item_info = {
                    "name": item.name,
                    "type": item_type,
                }
                if item.is_file():
                    item_info["size"] = item.stat().st_size
                result.append(item_info)
            return {"path": path, "entries": result}
        except Exception as e:
            return _error_result("list_failed", f"Failed to list {path}: {e}")

    return list_files


def create_glob_files(context: ToolRuntimeContext) -> Tool:
    """Create a glob_files tool for the given context."""

    @tool(description="Search for files using a glob pattern")
    def glob_files(pattern: str, path: str = ".") -> JSONValue:
        """Search for files using a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.py")
            path: Base directory, relative to workspace (default: ".")

        Returns:
            List of matching file paths or error dictionary
        """
        if not context.allow_read:
            return _error_result("read_disabled", "Read operations are disabled")

        try:
            base_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        if not base_path.exists():
            return _error_result("dir_not_found", f"Directory not found: {path}")

        if not base_path.is_dir():
            return _error_result("dir_not_found", f"Not a directory: {path}")

        try:
            matches = list(base_path.glob(pattern))
            # Use forward slashes consistently
            relative_paths = [str(m.relative_to(context.workspace.resolve())).replace("\\", "/") for m in matches]
            return {"pattern": pattern, "path": path, "matches": relative_paths}
        except Exception as e:
            return _error_result("glob_failed", f"Failed to glob {pattern}: {e}")

    return glob_files


def create_search_text(context: ToolRuntimeContext) -> Tool:
    """Create a search_text tool for the given context."""

    @tool(description="Search for text in files")
    def search_text(query: str, path: str = ".", include_pattern: str | None = None) -> JSONValue:
        """Search for text in files.

        Args:
            query: Text to search for
            path: Base directory, relative to workspace (default: ".")
            include_pattern: Optional glob pattern to filter files (e.g., "**/*.py")

        Returns:
            List of search results or error dictionary
        """
        if not context.allow_read:
            return _error_result("read_disabled", "Read operations are disabled")

        try:
            base_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        if not base_path.exists():
            return _error_result("dir_not_found", f"Directory not found: {path}")

        if not base_path.is_dir():
            return _error_result("dir_not_found", f"Not a directory: {path}")

        try:
            results: list[dict[str, Any]] = []
            count = 0

            glob_pattern = include_pattern or "**/*"
            for file_path in base_path.glob(glob_pattern):
                if count >= context.max_search_results:
                    break
                if not file_path.is_file():
                    continue

                # Skip large files
                if file_path.stat().st_size > context.max_file_size:
                    continue

                try:
                    lines = file_path.read_text().splitlines()
                    for line_num, line in enumerate(lines, 1):
                        if query in line:
                            if count >= context.max_search_results:
                                break
                            rel_path = str(file_path.relative_to(context.workspace.resolve())).replace("\\", "/")
                            results.append({
                                "path": rel_path,
                                "line": line_num,
                                "content": line,
                            })
                            count += 1
                except Exception:
                    continue

            return {
                "query": query,
                "path": path,
                "results": results,
                "truncated": count >= context.max_search_results,
            }
        except Exception as e:
            return _error_result("search_failed", f"Failed to search: {e}")

    return search_text


def create_write_file(context: ToolRuntimeContext) -> Tool:
    """Create a write_file tool for the given context."""

    @tool(description="Write content to a file")
    def write_file(path: str, content: str, encoding: str = "utf-8") -> JSONValue:
        """Write content to a file.

        Creates parent directories if needed. Overwrites existing files.

        Args:
            path: File path, relative to workspace
            content: Content to write
            encoding: File encoding (default: utf-8)

        Returns:
            Success info or error dictionary
        """
        if not context.allow_write:
            return _error_result("write_disabled", "Write operations are disabled")

        try:
            file_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding=encoding)
            return {
                "path": path,
                "size": len(content.encode(encoding)),
                "created": not file_path.exists() or file_path.stat().st_size == len(content),
            }
        except Exception as e:
            return _error_result("write_failed", f"Failed to write {path}: {e}")

    return write_file


def create_edit_file(context: ToolRuntimeContext) -> Tool:
    """Create an edit_file tool for the given context."""

    @tool(description="Edit a file by replacing old_text with new_text")
    def edit_file(path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> JSONValue:
        """Edit a file by replacing old_text with new_text.

        The old_text must match exactly and uniquely in the file.

        Args:
            path: File path, relative to workspace
            old_text: Text to find and replace (must be unique in the file)
            new_text: Replacement text
            encoding: File encoding (default: utf-8)

        Returns:
            Success info or error dictionary
        """
        if not context.allow_write:
            return _error_result("write_disabled", "Write operations are disabled")

        try:
            file_path = resolve_path(context.workspace, path)
        except ValueError:
            return _error_result(
                "path_outside_workspace",
                f"Path {path} is outside the workspace",
            )

        if not file_path.exists():
            return _error_result("file_not_found", f"File not found: {path}")

        if not file_path.is_file():
            return _error_result("file_not_found", f"Not a file: {path}")

        file_size = file_path.stat().st_size
        if file_size > context.max_file_size:
            return _error_result(
                "file_too_large",
                f"File {path} is {file_size} bytes, "
                f"max allowed is {context.max_file_size}",
            )

        try:
            content = file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return _error_result(
                "encoding_error",
                f"Failed to decode {path} with encoding {encoding}",
            )
        except Exception as e:
            return _error_result("read_failed", f"Failed to read {path}: {e}")

        # Check for unique match
        match_count = content.count(old_text)
        if match_count == 0:
            return _error_result(
                "no_match_found",
                f"No match found for old_text in {path}",
            )
        if match_count > 1:
            return _error_result(
                "multiple_matches",
                f"Found {match_count} matches for old_text in {path}, "
                f"must be unique",
            )

        try:
            new_content = content.replace(old_text, new_text)
            file_path.write_text(new_content, encoding=encoding)
            return {
                "path": path,
                "old_size": file_size,
                "new_size": len(new_content.encode(encoding)),
                "replacements": 1,
            }
        except Exception as e:
            return _error_result("edit_failed", f"Failed to edit {path}: {e}")

    return edit_file


def create_run_command(context: ToolRuntimeContext) -> Tool:
    """Create a run_command tool for the given context."""

    @tool(description="Run a command and return output")
    def run_command(
        command: str,
        args: list[str] | None = None,
        shell: bool = False,
    ) -> JSONValue:
        """Run a command and return output.

        Args:
            command: Command to run
            args: Optional list of arguments
            shell: Whether to use shell execution (default: False)

        Returns:
            Command result or error dictionary
        """
        if not context.allow_execute:
            return _error_result("execute_disabled", "Command execution is disabled")

        import time

        if args is None:
            args = []

        cmd_list: str | list[str]
        if shell:
            cmd_list = command + " " + " ".join(args) if args else command
        else:
            cmd_list = [command] + args

        start_time = time.time()
        timed_out = False
        proc: subprocess.Popen | None = None

        try:
            proc = subprocess.Popen(
                cmd_list,
                cwd=str(context.workspace.resolve()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                shell=shell,
            )

            stdout_bytes: bytes = b""
            stderr_bytes: bytes = b""
            stdout_truncated = False
            stderr_truncated = False

            # Read with timeout
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=context.command_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Kill and continue reading
                proc.kill()
                try:
                    stdout_bytes, stderr_bytes = proc.communicate(timeout=5.0)
                except Exception:
                    pass

            duration = time.time() - start_time
            exit_code = proc.returncode if proc.returncode is not None else -1

            # Decode output
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Truncate output if needed
            if len(stdout_bytes) > context.max_command_output:
                stdout = stdout[: context.max_command_output // 2] + "\n...[truncated]..."
                stdout_truncated = True
            if len(stderr_bytes) > context.max_command_output:
                stderr = stderr[: context.max_command_output // 2] + "\n...[truncated]..."
                stderr_truncated = True

            result: dict[str, Any] = {
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration": duration,
                "timed_out": timed_out,
            }
            if stdout_truncated or stderr_truncated:
                result["output_truncated"] = True

            return result
        except Exception as e:
            if timed_out:
                return _error_result(
                    "command_timed_out",
                    f"Command timed out after {context.command_timeout} seconds",
                )
            return _error_result("command_failed", f"Failed to run command: {e}")

    return run_command


def create_project_tools(context: ToolRuntimeContext) -> list[Tool]:
    """Create project tools for the given context.

    Args:
        context: Tool runtime context

    Returns:
        List of Tool objects based on context capabilities
    """
    tools: list[Tool] = []

    if context.allow_read:
        tools.append(create_read_file(context))
        tools.append(create_list_files(context))
        tools.append(create_glob_files(context))
        tools.append(create_search_text(context))

    if context.allow_write:
        tools.append(create_write_file(context))
        tools.append(create_edit_file(context))

    if context.allow_execute:
        tools.append(create_run_command(context))

    return tools