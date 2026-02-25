from __future__ import annotations

import base64
import ast
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional
import time
from urllib import error, parse, request

from .models import ComparisonResult

VLM_CACHE_VERSION = "v2"


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


def _extract_candidate_obj(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = payload.get("candidates", [])
    if not candidates:
        return None
    content = candidates[0].get("content", {})
    for part in content.get("parts", []):
        if isinstance(part.get("text"), str):
            continue
        if isinstance(part.get("json"), dict):
            return part["json"]
        if isinstance(part.get("inlineData"), dict):
            continue
    return None


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
    except json.JSONDecodeError as first_exc:
        parsed = None
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            candidate = cleaned[start : end + 1]
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(candidate)
                except (SyntaxError, ValueError):
                    parsed = None
        if parsed is None:
            try:
                parsed = ast.literal_eval(cleaned)
            except (SyntaxError, ValueError):
                parsed = None
        if parsed is None:
            partial: Dict[str, Any] = {}
            match_match = re.search(
                r'["\']?match["\']?\s*:\s*(true|false)', cleaned, re.IGNORECASE
            )
            if match_match:
                partial["match"] = match_match.group(1).lower() == "true"
            confidence_match = re.search(
                r'["\']?confidence["\']?\s*:\s*([0-9]*\.?[0-9]+)',
                cleaned,
                re.IGNORECASE,
            )
            if confidence_match:
                partial["confidence"] = float(confidence_match.group(1))
            reason_match = re.search(
                r'["\']?reason["\']?\s*:\s*["\']([^"\']*)',
                cleaned,
                re.IGNORECASE,
            )
            if reason_match:
                partial["reason"] = reason_match.group(1)
            if "match" in partial:
                return partial
            raise first_exc
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed


def _coerce_comparison_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {str(k).lower(): v for k, v in parsed.items()}
    if "match" not in normalized:
        raise ValueError("Model response missing 'match' field.")
    raw_match = normalized["match"]
    if isinstance(raw_match, bool):
        match_value = raw_match
    elif isinstance(raw_match, str):
        lowered = raw_match.strip().lower()
        if lowered in {"true", "yes", "1"}:
            match_value = True
        elif lowered in {"false", "no", "0"}:
            match_value = False
        else:
            raise ValueError("Model response 'match' value is not boolean.")
    else:
        match_value = bool(raw_match)
    reason = normalized.get("reason")
    confidence = normalized.get("confidence")
    return {
        "match": match_value,
        "reason": (
            str(reason)
            if reason is not None and str(reason).strip()
            else "Model response did not include reason."
        ),
        "confidence": float(confidence) if confidence is not None else None,
    }


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
        hasher.update(VLM_CACHE_VERSION.encode("utf-8"))
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
            "Return EXACTLY one JSON object on one line with keys:\n"
            '{"match": true|false, "reason": "short string", "confidence": 0.0}\n'
            "Rules: reason must be <= 8 words. confidence must be [0.0, 1.0]."
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
                "maxOutputTokens": 80,
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
                parsed_obj = _extract_candidate_obj(response_payload)
                if parsed_obj is None:
                    if not model_text:
                        return ComparisonResult(
                            match=False,
                            reason="Gemini returned no text payload for comparison.",
                            confidence=0.0,
                        )
                    parsed_obj = _parse_model_json(model_text)

                parsed = _coerce_comparison_payload(parsed_obj)
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
            except (json.JSONDecodeError, ValueError, SyntaxError) as exc:
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

