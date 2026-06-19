from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import ClipCandidate, SelectedClip
from backend.app.ports import ClipSelector


class _FakeClipSelector:
    def select(
        self, candidates: Sequence[ClipCandidate]
    ) -> Sequence[SelectedClip]:
        return tuple(
            SelectedClip(
                scene_id=candidate.scene_id,
                query_text=candidate.query_text,
                provider=candidate.provider,
                provider_clip_id=candidate.provider_clip_id,
                title=candidate.title,
                preview_url=candidate.preview_url,
                source_url=candidate.source_url,
                duration_seconds=candidate.duration_seconds,
                width=candidate.width,
                height=candidate.height,
                selection_reason="fake",
            )
            for candidate in candidates[:1]
        )


def test_fake_satisfies_clip_selector_protocol() -> None:
    assert isinstance(_FakeClipSelector(), ClipSelector)


def test_fake_can_return_selected_clips() -> None:
    selector: ClipSelector = _FakeClipSelector()
    candidate = ClipCandidate(
        scene_id="scene-1",
        query_text="modern office workspace",
        provider="fake",
        provider_clip_id="scene-1-fake",
        title="modern office workspace fake candidate",
        preview_url="memory://clips/scene-1/preview.jpg",
        source_url="memory://clips/scene-1",
        duration_seconds=4.0,
        width=1280,
        height=720,
    )

    selected = selector.select((candidate,))

    assert isinstance(selected, Sequence)
    assert selected == (
        SelectedClip(
            scene_id="scene-1",
            query_text="modern office workspace",
            provider="fake",
            provider_clip_id="scene-1-fake",
            title="modern office workspace fake candidate",
            preview_url="memory://clips/scene-1/preview.jpg",
            source_url="memory://clips/scene-1",
            duration_seconds=4.0,
            width=1280,
            height=720,
            selection_reason="fake",
        ),
    )


def test_clip_selector_resolves_from_provider_ports() -> None:
    assert inspect.getmodule(ClipSelector).__name__ == (
        "backend.app.ports.providers"
    )


def test_clip_selector_contract_uses_candidate_and_selected_clip_sequences() -> None:
    hints = get_type_hints(ClipSelector.select)

    assert hints["candidates"] == Sequence[ClipCandidate]
    assert hints["return"] == Sequence[SelectedClip]
