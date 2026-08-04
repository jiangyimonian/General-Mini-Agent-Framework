# 1.1.1 Project Tools Implementation Plan

## Goal

Implement the 1.1.1 project toolset with ToolRuntimeContext, read tools, write tools, and execute tools.

## Tasks

### Task 1: ToolRuntimeContext and Path Security

- [ ] Create `general_mini_agent/tools_project.py`
- [ ] Implement `ToolRuntimeContext` dataclass
- [ ] Implement `resolve_path()` helper for secure path resolution
- [ ] Add tests for path security
- [ ] Commit: `feat: add ToolRuntimeContext and path security`

### Task 2: Read Tools

- [ ] Implement `read_file()` tool
- [ ] Implement `list_files()` tool
- [ ] Implement `glob_files()` tool
- [ ] Implement `search_text()` tool
- [ ] Add tests for read tools
- [ ] Commit: `feat: add read tools (read_file, list_files, glob_files, search_text)`

### Task 3: Write Tools

- [ ] Implement `write_file()` tool
- [ ] Implement `edit_file()` tool with unique matching
- [ ] Add tests for write tools
- [ ] Commit: `feat: add write tools (write_file, edit_file)`

### Task 4: Execute Tool

- [ ] Implement `run_command()` tool with timeout
- [ ] Add tests for command execution
- [ ] Commit: `feat: add run_command tool`

### Task 5: Factory Function and Integration

- [ ] Implement `create_project_tools()` factory
- [ ] Add integration tests
- [ ] Update exports in `__init__.py` (optional)
- [ ] Commit: `feat: add create_project_tools factory`

## Testing

- All tests use temporary directories
- Path security tests verify escape attempts
- Edit tool tests verify unique matching
- Command tests verify timeout and output limits
- Test Windows and POSIX path behavior with `Path`

## Global Constraints

- No automatic tool registration
- `allow_write` and `allow_execute` default to `False`
- All paths are relative to workspace
- All tools return structured results with error codes