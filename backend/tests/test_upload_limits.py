"""Tests for bounded administrator upload reads."""

from types import SimpleNamespace

import pytest

from app.api.v1 import identity
from app.core.errors import ValidationError


class FakeUpload:
    def __init__(
        self,
        data: bytes,
        *,
        size: int | None,
    ) -> None:
        self.data = data
        self.size = size
        self.requested_read_size: int | None = None
        self.read_called = False

    async def read(
        self,
        size: int = -1,
    ) -> bytes:
        self.read_called = True
        self.requested_read_size = size

        if size < 0:
            return self.data

        return self.data[:size]


@pytest.mark.asyncio
async def test_reported_oversized_upload_is_rejected_before_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        identity,
        "get_settings",
        lambda: SimpleNamespace(max_upload_bytes=4),
    )

    file = FakeUpload(
        b"12345",
        size=5,
    )

    with pytest.raises(
        ValidationError,
        match="maximum upload size",
    ):
        await identity._read_upload_with_limit(file)

    assert file.read_called is False


@pytest.mark.asyncio
async def test_unknown_size_upload_uses_bounded_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        identity,
        "get_settings",
        lambda: SimpleNamespace(max_upload_bytes=4),
    )

    file = FakeUpload(
        b"123456789",
        size=None,
    )

    with pytest.raises(
        ValidationError,
        match="maximum upload size",
    ):
        await identity._read_upload_with_limit(file)

    assert file.requested_read_size == 5


@pytest.mark.asyncio
async def test_upload_within_limit_is_returned(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        identity,
        "get_settings",
        lambda: SimpleNamespace(max_upload_bytes=4),
    )

    file = FakeUpload(
        b"1234",
        size=None,
    )

    raw = await identity._read_upload_with_limit(file)

    assert raw == b"1234"
    assert file.requested_read_size == 5
