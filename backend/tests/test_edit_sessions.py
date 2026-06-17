import json

import pytest

import app.edit_sessions as edit_sessions
from app.edit_sessions import (
    EditSessionError,
    apply_patch_set,
    propose_patch,
    replace_in_file,
    rollback_patch_set,
    run_whitelisted_command,
    write_file,
)


def runtime_for(root, **overrides):
    data = {
        "allowedRootsJson": json.dumps([str(root)]),
        "maxPatchBytes": 524288,
        "maxCommandOutputBytes": 4096,
        "allowedCommandProfilesJson": json.dumps(["git status", "python -m compileall"]),
        "allowDirectEdits": False,
    }
    data.update(overrides)
    return data


def test_propose_apply_and_rollback_structured_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    source = tmp_path / "app.py"
    source.write_text("print('old')\n", encoding="utf-8")
    runtime = runtime_for(tmp_path)

    proposed = propose_patch({"path": "app.py", "original": "old", "replacement": "new"}, runtime)
    assert proposed["status"] == "proposed"
    assert proposed["files"][0]["path"] == "app.py"

    applied = apply_patch_set(proposed["patchId"], runtime)
    assert applied["status"] == "applied"
    assert applied["rollbackId"]
    assert source.read_text(encoding="utf-8") == "print('new')\n"

    rolled_back = rollback_patch_set(applied["rollbackId"])
    assert rolled_back["status"] == "rolled_back"
    assert source.read_text(encoding="utf-8") == "print('old')\n"


def test_propose_patch_rejects_path_outside_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(EditSessionError):
        propose_patch({"path": str(outside), "original": "x", "replacement": "y"}, runtime_for(tmp_path))


def test_apply_rejects_stale_base_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    source = tmp_path / "app.py"
    source.write_text("old\n", encoding="utf-8")
    runtime = runtime_for(tmp_path)
    proposed = propose_patch({"path": "app.py", "original": "old", "replacement": "new"}, runtime)
    source.write_text("changed\n", encoding="utf-8")

    with pytest.raises(EditSessionError):
        apply_patch_set(proposed["patchId"], runtime)


def test_replace_in_file_requires_direct_edit_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")

    with pytest.raises(EditSessionError):
        replace_in_file({"path": "app.py", "search": "old", "replace": "new"}, runtime_for(tmp_path))

    result = replace_in_file(
        {"path": "app.py", "search": "old", "replace": "new"},
        runtime_for(tmp_path, allowDirectEdits=True),
    )
    assert result["status"] == "applied"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_write_file_default_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    target = tmp_path / "new.txt"
    runtime = runtime_for(tmp_path, allowDirectEdits=True)

    write_file({"path": "new.txt", "content": "hello"}, runtime)
    assert target.read_text(encoding="utf-8") == "hello"

    with pytest.raises(EditSessionError):
        write_file({"path": "new.txt", "content": "override"}, runtime)

    write_file({"path": "new.txt", "content": "override", "overwrite": True}, runtime)
    assert target.read_text(encoding="utf-8") == "override"


def test_write_file_rejects_existing_empty_file_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_sessions, "EDIT_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(edit_sessions, "ROOT_DIR", tmp_path)
    (tmp_path / "sessions").mkdir()
    target = tmp_path / "empty.txt"
    target.write_text("", encoding="utf-8")

    with pytest.raises(EditSessionError):
        write_file({"path": "empty.txt", "content": "content"}, runtime_for(tmp_path, allowDirectEdits=True))


def test_run_whitelisted_command_rejects_unlisted_command(tmp_path):
    runtime = runtime_for(tmp_path)
    result = run_whitelisted_command({"command": "python -m compileall .", "cwd": "."}, runtime)
    assert "exitCode" in result

    with pytest.raises(EditSessionError):
        run_whitelisted_command({"command": "git reset --hard", "cwd": "."}, runtime)
