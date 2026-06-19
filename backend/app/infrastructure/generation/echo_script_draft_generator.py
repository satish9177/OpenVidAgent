"""Deterministic local script-draft adapter.

A composition-root default that turns a prompt into a usable script draft without
any randomness, network, provider SDK, or subprocess. It echoes the prompt and
language into a small fixed template so output is reproducible and the inputs are
observable. A real LLM-backed adapter can replace it later behind the same port.
"""

from __future__ import annotations

from backend.app.ports import ScriptDraftGenerator


class EchoScriptDraftGenerator(ScriptDraftGenerator):
    def generate(self, prompt: str, language: str) -> str:
        return (
            "# Draft script\n"
            f"Language: {language}\n"
            f"Topic: {prompt}\n"
            "\n"
            f"Welcome. In this video we cover: {prompt}.\n"
            "Thanks for watching."
        )
