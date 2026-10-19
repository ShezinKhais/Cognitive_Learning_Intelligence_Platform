"""The evidence scripts only ever touch a database named as a scratch one."""

import pytest

from scripts.db_evidence import require_scratch_name, scratch_url


@pytest.mark.parametrize("name", ["clip_evidence", "clip_evidence_history", "evidence2"])
def test_a_scratch_name_is_allowed(name: str) -> None:
    require_scratch_name(name)


@pytest.mark.parametrize("name", ["clip", "postgres", "clip_history", "production"])
def test_any_other_name_is_refused(name: str) -> None:
    with pytest.raises(SystemExit, match="not a scratch database"):
        require_scratch_name(name)


def test_no_connection_is_built_for_a_real_database_name() -> None:
    with pytest.raises(SystemExit, match="not a scratch database"):
        scratch_url("clip")
