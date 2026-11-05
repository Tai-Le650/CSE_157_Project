from __future__ import annotations

import copy
import logging
import re

TOKEN_PATTERN = re.compile(r"(token=)[^&\s\"']+")
REDACTED = r"\1[redacted]"


def redact(text: str) -> str:
    return TOKEN_PATTERN.sub(REDACTED, text)


def _redact_value(value):
    return redact(value) if isinstance(value, str) else value


class RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_value(value) for key, value in record.args.items()}
        return True


def uvicorn_log_config() -> dict:
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["redact_token"] = {"()": RedactTokenFilter}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).append("redact_token")
    return config
