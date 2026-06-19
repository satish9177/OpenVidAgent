"""Deterministic metadata-only clip selector.

Chooses the first candidate per scene/query group without network, SDK,
filesystem, ranking, scoring, or subprocess behavior.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain import ClipCandidate, SelectedClip
from backend.app.ports import ClipSelector

_SELECTION_REASON = "first_candidate_for_scene_query"


class DeterministicClipSelector(ClipSelector):
    def select(
        self, candidates: Sequence[ClipCandidate]
    ) -> Sequence[SelectedClip]:
        seen: set[tuple[str, str]] = set()
        selected: list[SelectedClip] = []

        for candidate in candidates:
            group_key = (candidate.scene_id, candidate.query_text)
            if group_key in seen:
                continue
            seen.add(group_key)
            selected.append(_selected_from_candidate(candidate))

        return tuple(selected)


def _selected_from_candidate(candidate: ClipCandidate) -> SelectedClip:
    return SelectedClip(
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
        selection_reason=_SELECTION_REASON,
    )
