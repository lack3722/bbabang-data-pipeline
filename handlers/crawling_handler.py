"""AWS Lambda entry point for BBABANG crawling."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from bbabang_pipeline.config import ROOM_ID_END, ROOM_ID_START, now_kst
from bbabang_pipeline.extract import run_extract

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_int(event: dict[str, Any], key: str, default: int) -> int:
    """Lambda event에서 정수 설정값을 안전하게 읽는다."""
    value = event.get(key, default)
    if value in (None, ""):
        return default

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key}는 정수여야 합니다. 입력값={value!r}") from exc


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """기존 run_extract()를 호출하는 Crawling Lambda Handler."""
    event = event or {}

    started_at = now_kst()
    room_id_start = _get_int(event, "room_id_start", ROOM_ID_START)
    room_id_end = _get_int(event, "room_id_end", ROOM_ID_END)
    request_id = getattr(context, "aws_request_id", None)

    logger.info(
        "BBABANG crawling started. request_id=%s start=%s end=%s",
        request_id,
        room_id_start,
        room_id_end,
    )

    try:
        raw_csv_file: Path = run_extract(
            room_id_start=room_id_start,
            room_id_end=room_id_end,
        )

        body = {
            "success": True,
            "message": "BBABANG crawling completed.",
            "request_id": request_id,
            "room_id_start": room_id_start,
            "room_id_end": room_id_end,
            "raw_csv_file": str(raw_csv_file),
            "started_at": started_at.isoformat(),
            "finished_at": now_kst().isoformat(),
        }

        return {
            "statusCode": 200,
            "body": json.dumps(body, ensure_ascii=False),
        }

    except Exception:
        logger.exception(
            "BBABANG crawling failed. request_id=%s",
            request_id,
        )
        raise
