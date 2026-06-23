"""
piston_client.py
-----------------
Tool/API Integration layer for DebugMate.

Uses the free, public Piston code-execution API (https://piston.readthedocs.io)
run by emkc.org. No API key, no auth, generous rate limit, great for a
beginner-friendly "Tool" capability: the agent can actually RUN the fixed
code and show real output, not just guess.

If the API is unreachable or the language/version can't be resolved, the
agent falls back gracefully (Capability 2 explicitly requires this).
"""

import httpx
from typing import Any, Dict, Optional

PISTON_BASE = "https://emkc.org/api/v2/piston"

# A few sane aliases so user-typed language names map to what Piston expects.
LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "c++": "cpp",
    "cplusplus": "cpp",
    "c#": "csharp",
    "ts": "typescript",
    "rb": "ruby",
    "golang": "go",
}

_runtime_cache: Optional[Dict[str, str]] = None


def _normalize_language(language: str) -> str:
    lang = (language or "").strip().lower()
    return LANGUAGE_ALIASES.get(lang, lang)


def _get_runtimes() -> Dict[str, str]:
    """Fetch and cache {language: latest_version} from Piston."""
    global _runtime_cache
    if _runtime_cache is not None:
        return _runtime_cache
    try:
        resp = httpx.get(f"{PISTON_BASE}/runtimes", timeout=10.0)
        resp.raise_for_status()
        runtimes = resp.json()
        cache: Dict[str, str] = {}
        for rt in runtimes:
            lang = rt.get("language")
            version = rt.get("version")
            if lang and version:
                # Runtimes list is ordered; keep first (latest) version seen.
                cache.setdefault(lang, version)
            for alias in rt.get("aliases", []):
                cache.setdefault(alias, version)
        _runtime_cache = cache
        return cache
    except (httpx.HTTPError, ValueError):
        _runtime_cache = {}
        return {}


def execute_code(language: str, code: str, stdin: str = "") -> Dict[str, Any]:
    """
    Executes `code` in `language` using the Piston API.

    Returns a dict with keys: ok, stdout, stderr, output, version, error.
    Never raises -- callers always get a usable fallback result.
    """
    norm_lang = _normalize_language(language)
    if not norm_lang:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output": "",
            "version": None,
            "error": "No language specified, so the code could not be executed.",
        }

    runtimes = _get_runtimes()
    version = runtimes.get(norm_lang)

    if not version:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output": "",
            "version": None,
            "error": f"'{language}' isn't supported by the live execution sandbox right now. "
                     f"Showing the analysis and fix without a live run.",
        }

    payload = {
        "language": norm_lang,
        "version": version,
        "files": [{"name": "main", "content": code}],
        "stdin": stdin,
    }

    try:
        resp = httpx.post(f"{PISTON_BASE}/execute", json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        run = data.get("run", {})
        compile_step = data.get("compile", {})

        stderr = (compile_step.get("stderr") or "") + (run.get("stderr") or "")
        stdout = run.get("stdout") or ""
        ok = run.get("code", 1) == 0 and not stderr.strip()

        return {
            "ok": ok,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "output": (run.get("output") or "").strip(),
            "version": version,
            "error": None,
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "output": "",
            "version": version,
            "error": f"The live execution sandbox is unreachable right now ({exc.__class__.__name__}). "
                     f"Showing the analysis and fix without a live run.",
        }
