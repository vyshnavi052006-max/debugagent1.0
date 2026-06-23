"""
agent.py
--------
DebugMate's brain: ties together Perception -> Reasoning/Planning -> Action,
backed by the Memory and Tool layers.

Pipeline for every user message (Capability 1 - Multi-Step Planning):
  1. PERCEIVE   - is this a coding/debugging request at all? (domain guard)
  2. PLAN       - break the request into: Analyze -> Diagnose -> Fix -> Run -> Explain
  3. ACT        - call Groq for reasoning/fix text, call Piston to execute code (Capability 2)
  4. REMEMBER   - store language, bug type, and fix summary (Capability 3)
  5. DECIDE     - use memory to personalize the explanation / catch repeat bugs

DebugMate intentionally refuses anything outside the coding/debugging domain,
per the project's "stay in your assigned domain" requirement.
"""

import re
import uuid
from typing import Any, Dict, List, Optional

import groq_client
from memory import MemoryStore
from piston_client import execute_code

CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```")

CODING_KEYWORDS = (
    "error", "bug", "traceback", "exception", "stack trace", "debug", "fix",
    "crash", "fails", "not working", "doesn't work", "undefined", "null pointer",
    "syntax error", "compile", "runtime error", "code", "function", "def ",
    "class ", "import ", "console.log", "print(", "segfault", "exit code",
    "indexerror", "keyerror", "typeerror", "valueerror", "nullreferenceexception",
)

LANGUAGE_HINTS = {
    "python": ["def ", "import ", "print(", "elif", "self.", "indentationerror", ".py"],
    "javascript": ["console.log", "function(", "=>", "const ", "let ", "undefined is not", ".js"],
    "java": ["public static void main", "system.out.println", ".java", "nullpointerexception"],
    "cpp": ["#include", "std::", "cout <<", ".cpp"],
    "c": ["#include <stdio.h>", "printf(", "scanf("],
    "csharp": ["console.writeline", "using system", ".cs"],
    "go": ["package main", "fmt.println", ".go"],
    "ruby": ["puts ", "def end", ".rb"],
    "typescript": [": string", ": number", ".ts"],
}


def _extract_code_block(message: str) -> Optional[Dict[str, str]]:
    match = CODE_BLOCK_RE.search(message)
    if not match:
        return None
    lang = (match.group(1) or "").lower().strip()
    code = match.group(2).strip()
    return {"language": lang, "code": code}


def _guess_language(text: str) -> Optional[str]:
    lowered = text.lower()
    for lang, hints in LANGUAGE_HINTS.items():
        if any(hint in lowered for hint in hints):
            return lang
    return None


def _quick_domain_guess(message: str) -> Optional[bool]:
    """Fast heuristic so we don't burn an LLM call on obvious cases."""
    if _extract_code_block(message):
        return True
    lowered = message.lower()
    if any(kw in lowered for kw in CODING_KEYWORDS):
        return True
    if len(message.strip()) < 3:
        return False
    return None  # ambiguous -> let the LLM decide


class DebugMateAgent:
    name = "DebugMate"
    domain = "Code Debugging"

    def __init__(self):
        self.memory = MemoryStore()

    # ---------- Capability: domain guard ----------
    def _is_coding_query(self, message: str) -> bool:
        guess = _quick_domain_guess(message)
        if guess is not None:
            return guess
        try:
            verdict = groq_client.ask(
                system_prompt=(
                    "You are a strict classifier. Reply with exactly one word: "
                    "'yes' if the user's message is about programming, code, software bugs, "
                    "errors, or debugging. Reply 'no' for anything else (general chit-chat, "
                    "other topics, unrelated questions)."
                ),
                user_prompt=message,
                temperature=0.0,
                max_tokens=5,
            )
            return verdict.strip().lower().startswith("y")
        except RuntimeError:
            # No API key configured yet -- be permissive locally rather than crash.
            return True

    # ---------- Main entry point ----------
    def handle(self, session_id: Optional[str], message: str) -> Dict[str, Any]:
        session_id = session_id or str(uuid.uuid4())
        steps: List[Dict[str, Any]] = []

        if not self._is_coding_query(message):
            return {
                "session_id": session_id,
                "domain_match": False,
                "steps": [],
                "final_answer": (
                    "I'm DebugMate \u2014 I only help with code debugging: finding bugs, "
                    "explaining errors, fixing snippets, and running code to verify the fix. "
                    "Paste an error message or a code snippet and I'll get to work."
                ),
                "memory_snapshot": self.memory.snapshot(session_id),
            }

        block = _extract_code_block(message)
        code = block["code"] if block else None
        language = (block["language"] if block and block["language"] else _guess_language(message))

        session = self.memory.get_session(session_id)
        if not language:
            language = session.get("preferred_language")

        # ---- STEP 1: Analyze ----
        analysis = groq_client.ask(
            system_prompt=(
                "You are DebugMate, an expert code debugging agent. Analyze the user's report "
                "(code and/or error message) concisely. Identify the symptom and the likely "
                "language if not stated. Keep it to 2-3 sentences."
            ),
            user_prompt=message,
            temperature=0.2,
            max_tokens=220,
        )
        steps.append({"name": "Analyze", "detail": analysis})

        # ---- STEP 2: Diagnose root cause ----
        diagnosis = groq_client.ask(
            system_prompt=(
                "You are DebugMate. Given this analysis of a bug report, state the single most "
                "likely root cause in 1-2 sentences, and a short bug_type label (e.g. "
                "'IndexError', 'off-by-one', 'null reference', 'logic error', 'syntax error'). "
                "Format exactly as:\nRootCause: <text>\nBugType: <label>"
            ),
            user_prompt=f"Analysis: {analysis}\n\nOriginal report: {message}",
            temperature=0.2,
            max_tokens=150,
        )
        root_cause = diagnosis
        bug_type = "general bug"
        m = re.search(r"BugType:\s*(.+)", diagnosis)
        if m:
            bug_type = m.group(1).strip()
        steps.append({"name": "Diagnose Root Cause", "detail": root_cause})

        # ---- STEP 3: Generate fix ----
        fix_prompt = (
            f"Original report:\n{message}\n\nRoot cause:\n{root_cause}\n\n"
            "Provide the corrected, complete code in a single fenced code block "
            "(```language ... ```). After the code block, add nothing else."
        )
        fix_response = groq_client.ask(
            system_prompt=(
                "You are DebugMate, an expert software engineer. Fix the bug. Return ONLY a "
                "single fenced code block with the corrected, runnable code. No prose outside the block."
            ),
            user_prompt=fix_prompt,
            temperature=0.2,
            max_tokens=700,
        )
        fixed_block = _extract_code_block(fix_response)
        fixed_code = fixed_block["code"] if fixed_block else fix_response.strip()
        fixed_lang = (fixed_block["language"] if fixed_block and fixed_block["language"] else language)
        steps.append({"name": "Generate Fix", "detail": f"```{fixed_lang or ''}\n{fixed_code}\n```"})

        # ---- STEP 4: Execute fixed code (Tool/API capability) ----
        execution_result = None
        if fixed_lang and fixed_code:
            execution_result = execute_code(fixed_lang, fixed_code)
            if execution_result["ok"]:
                exec_detail = (
                    f"Ran the fix with the live sandbox ({fixed_lang} {execution_result['version']}).\n"
                    f"Output:\n{execution_result['stdout'] or '(no stdout)'}"
                )
            else:
                exec_detail = (
                    execution_result.get("error")
                    or f"Sandbox ran it but it still produced an error:\n{execution_result['stderr']}"
                )
            steps.append({"name": "Execute Fix", "detail": exec_detail, "execution_result": execution_result})
        else:
            steps.append({
                "name": "Execute Fix",
                "detail": "No runnable language detected, so the live sandbox step was skipped.",
                "execution_result": None,
            })

        # ---- STEP 5: Explain (memory-personalized) ----
        common_bugs = self.memory.common_bug_types(session_id)
        memory_hint = ""
        if bug_type.lower() in [b.lower() for b in common_bugs]:
            memory_hint = (
                f" Note: you've hit a '{bug_type}' bug before in this session \u2014 "
                "I'll flag the pattern so it's easier to spot next time."
            )

        explanation = groq_client.ask(
            system_prompt=(
                "You are DebugMate. Explain the bug and fix in plain English for a learner. "
                "3-5 sentences: what was wrong, why it broke, how the fix solves it, and one tip "
                "to avoid this bug class in future."
            ),
            user_prompt=f"Root cause: {root_cause}\nFix:\n{fixed_code}",
            temperature=0.4,
            max_tokens=300,
        )
        explanation = explanation + memory_hint
        steps.append({"name": "Explain", "detail": explanation})

        # ---- Remember (Capability 3) ----
        self.memory.add_bug_record(session_id, fixed_lang, bug_type, root_cause[:200])
        self.memory.update_session(session_id, last_code=fixed_code, task_progress="completed last debug cycle")

        final_answer = self._compose_final_answer(fixed_lang, fixed_code, explanation, execution_result)

        return {
            "session_id": session_id,
            "domain_match": True,
            "steps": steps,
            "final_answer": final_answer,
            "memory_snapshot": self.memory.snapshot(session_id),
        }

    def _compose_final_answer(
        self,
        language: Optional[str],
        fixed_code: str,
        explanation: str,
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        parts = [f"**Fixed code:**\n```{language or ''}\n{fixed_code}\n```", f"\n**Explanation:** {explanation}"]
        if execution_result:
            if execution_result.get("ok"):
                parts.append(f"\n**Live run output:**\n```\n{execution_result.get('stdout') or '(no output)'}\n```")
            elif execution_result.get("error"):
                parts.append(f"\n**Sandbox note:** {execution_result['error']}")
            elif execution_result.get("stderr"):
                parts.append(f"\n**Sandbox stderr:**\n```\n{execution_result['stderr']}\n```")
        return "\n".join(parts)

    def remember_constraint(self, session_id: str, constraint: str) -> None:
        self.memory.add_constraint(session_id, constraint)
