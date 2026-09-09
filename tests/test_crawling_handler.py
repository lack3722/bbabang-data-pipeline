from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from handlers import crawling_handler


def test_lambda_handler_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, int] = {}

    def fake_run_extract(room_id_start: int, room_id_end: int) -> Path:
        called["room_id_start"] = room_id_start
        called["room_id_end"] = room_id_end
        return Path("/tmp/bbabang-data/raw/bbabang_reviews_raw.csv")

    monkeypatch.setattr(crawling_handler, "run_extract", fake_run_extract)

    result = crawling_handler.lambda_handler(
        {"room_id_start": 4008, "room_id_end": 4007},
        SimpleNamespace(aws_request_id="test-request-id"),
    )

    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert body["success"] is True
    assert body["request_id"] == "test-request-id"
    assert called == {"room_id_start": 4008, "room_id_end": 4007}


def test_lambda_handler_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, int] = {}

    def fake_run_extract(room_id_start: int, room_id_end: int) -> Path:
        received["start"] = room_id_start
        received["end"] = room_id_end
        return Path("/tmp/result.csv")

    monkeypatch.setattr(crawling_handler, "run_extract", fake_run_extract)

    result = crawling_handler.lambda_handler(
        {},
        SimpleNamespace(aws_request_id="default-test"),
    )

    assert result["statusCode"] == 200
    assert received["start"] == crawling_handler.ROOM_ID_START
    assert received["end"] == crawling_handler.ROOM_ID_END


def test_lambda_handler_rejects_invalid_room_id() -> None:
    with pytest.raises(ValueError, match="room_id_start는 정수여야 합니다"):
        crawling_handler.lambda_handler(
            {"room_id_start": "abc"},
            None,
        )
