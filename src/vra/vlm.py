from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import time
from urllib import error, parse, request

from .models import ComparisonResult


def _encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _extract_response_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    content = candidates[0].get("content", {})
    for part in content.get("parts", []):
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_model_json(text: str) -> Dict[str, Any]:
    cleaned = _strip_json_fence(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed


class VLMClient:
    """Gemini VLM adapter for 4-image protocol/report comparison."""

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        api_key: Optional[str] = None,
        timeout_seconds: int = 45,
    ) -> None:
        env_model = os.getenv("GEMINI_MODEL", "").strip()
        self.model_name = env_model or model_name
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds
        self.min_seconds_between_calls = float(
            os.getenv("GEMINI_MIN_SECONDS_BETWEEN_CALLS", "0.5")
        )
        self.max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "2"))
        self._last_request_at = 0.0
        cache_default = Path(".cache") / "vlm_cache.json"
        self.cache_path = Path(os.getenv("VLM_CACHE_PATH", str(cache_default)))
        self.cache_enabled = os.getenv("VLM_CACHE_DISABLE", "").strip().lower() not in {
            "1",
            "true",
            "yes",
        }
        self._cache: Dict[str, Dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        if not self.cache_enabled or not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {
                    key: value
                    for key, value in payload.items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
        except (OSError, json.JSONDecodeError):
            return {}
        return {}

    def _save_cache(self) -> None:
        if not self.cache_enabled:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _cache_key(
        self,
        pq_master: Path,
        pq_sample: Path,
        report_master: Path,
        report_sample: Path,
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(self.model_name.encode("utf-8"))
        for path in (pq_master, pq_sample, report_master, report_sample):
            hasher.update(path.read_bytes())
        return hasher.hexdigest()

    def _throttle(self) -> None:
        if self.min_seconds_between_calls <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.min_seconds_between_calls:
            time.sleep(self.min_seconds_between_calls - elapsed)

    def compare(
        self,
        pq_master: Optional[Path],
        pq_sample: Optional[Path],
        report_master: Optional[Path],
        report_sample: Optional[Path],
    ) -> ComparisonResult:
        if report_master is None or report_sample is None:
            return ComparisonResult(
                match=False,
                reason="Missing report crops for this repeat/difference.",
                confidence=0.0,
            )
        if pq_master is None or pq_sample is None:
            return ComparisonResult(
                match=False,
                reason="Missing protocol crops for this repeat/difference.",
                confidence=0.0,
            )

        if not self.api_key:
            return ComparisonResult(
                match=False,
                reason="Gemini API key not configured (set GEMINI_API_KEY).",
                confidence=0.0,
            )
        cache_key = self._cache_key(pq_master, pq_sample, report_master, report_sample)
        if self.cache_enabled and cache_key in self._cache:
            return ComparisonResult.model_validate(self._cache[cache_key])

        prompt = (
            "You are validating a PQ protocol row against a report row.\n"
            "You will receive 4 images in order:\n"
            "1) protocol master, 2) protocol sample, 3) report master, 4) report sample.\n"
            "Decide if the report pair matches the protocol pair for the same difference ID.\n"
            "Return ONLY strict JSON with keys:\n"
            '{"match": boolean, "reason": string, "confidence": number}\n'
            "Use confidence in [0.0, 1.0]."
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": _encode_image(pq_master),
                            }
                        },
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": _encode_image(pq_sample),
                            }
                        },
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": _encode_image(report_master),
                            }
                        },
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": _encode_image(report_sample),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 300,
            },
        }
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:"
            "generateContent"
        )
        url = endpoint + "?" + parse.urlencode({"key": self.api_key})
        req = request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    response_payload = json.loads(resp.read().decode("utf-8"))
                self._last_request_at = time.time()
                model_text = _extract_response_text(response_payload)
                if not model_text:
                    return ComparisonResult(
                        match=False,
                        reason="Gemini returned no text payload for comparison.",
                        confidence=0.0,
                    )

                parsed = _parse_model_json(model_text)
                result = ComparisonResult.model_validate(parsed)
                if result.confidence is not None:
                    result.confidence = max(0.0, min(1.0, float(result.confidence)))
                if self.cache_enabled:
                    self._cache[cache_key] = result.model_dump()
                    self._save_cache()
                return result
            except error.HTTPError as exc:
                last_error = exc
                self._last_request_at = time.time()
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                break
            except (error.URLError, TimeoutError) as exc:
                last_error = exc
                self._last_request_at = time.time()
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                break
            except (json.JSONDecodeError, ValueError) as exc:
                return ComparisonResult(
                    match=False,
                    reason=f"Gemini response parsing failed: {exc}",
                    confidence=0.0,
                )

        return ComparisonResult(
            match=False,
            reason=f"Gemini API request failed: {last_error}",
            confidence=0.0,
        )

