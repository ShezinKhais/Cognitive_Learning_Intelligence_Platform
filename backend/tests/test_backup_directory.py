"""The backup folder is closed to everyone but the owner before any dump is written."""

import stat
import subprocess

import pytest

from scripts import database_backup


def test_a_loose_backup_folder_is_closed_before_dumping(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    folder.chmod(0o755)

    def refuse(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "pg_dump")

    monkeypatch.setattr(database_backup.subprocess, "run", refuse)

    with pytest.raises(subprocess.CalledProcessError):
        database_backup.dump("postgresql://user:secret@localhost/db", folder, "clip")

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert list(folder.iterdir()) == []
