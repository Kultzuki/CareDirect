"""Durable local quota reservations shared by processes; failures retain their reservation."""

import hashlib
import sqlite3
import time
from pathlib import Path

from app.extraction.adapter import ExtractionUnavailable


class GeminiQuota:
    def __init__(self, path: Path, key: str, *, rpm=5, tpm=250000, rpd=20):
        self.path = path
        self.scope = hashlib.sha256(key.strip().encode()).hexdigest()
        self.rpm, self.tpm, self.rpd = min(rpm, 5), min(tpm, 250000), min(rpd, 20)

    def reserve(self, tokens=0, *, now=None, required_calls=1):
        now = time.time() if now is None else now
        if tokens < 0 or tokens > self.tpm:
            raise ExtractionUnavailable("Document exceeds the Gemini input-token allowance.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests (scope TEXT, at REAL, tokens INTEGER)"
            )
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT at, tokens FROM requests WHERE scope=? AND at>?", (self.scope, now - 86400)
            ).fetchall()
            if len(rows) + required_calls > self.rpd:
                raise ExtractionUnavailable(
                    "Gemini local daily allowance reached. Try after the 24-hour window expires."
                )
            minute = [(at, count) for at, count in rows if at > now - 60]
            if (
                len(minute) + required_calls > self.rpm
                or sum(count for _, count in minute) + tokens > self.tpm
            ):
                raise ExtractionUnavailable(
                    "Gemini minute allowance reached. Wait a minute before retrying."
                )
            connection.execute("INSERT INTO requests VALUES (?, ?, ?)", (self.scope, now, tokens))
