from __future__ import annotations

import pytest

from backend.app.domain import SceneSpec, SelectedClip, VideoAssemblySegment
from backend.app.infrastructure.generation import (
    DeterministicVideoAssemblyPlanner,
)
from backend.app.ports import VideoAssemblyPlanner
from tests.fakes import FakeVideoAssemblyPlanner


def _scene(
    scene_id: str,
    *,
    duration_seconds: float = 6.0,
) -> SceneSpec:
    return SceneSpec(
        scene_id=scene_id,
        narration=f"Narration for {scene_id}",
        visual_query=f"Visual query for {scene_id}",
        duration_seconds=duration_seconds,
    )


def _selected_clip(
    scene_id: str,
    index: int,
    *,
    duration_seconds: float = 9.0,
) -> SelectedClip:
    return SelectedClip(
        scene_id=scene_id,
        query_text=f"query {scene_id} {index}",
        provider="stub",
        provider_clip_id=f"{scene_id}-{index}",
        title=f"Clip {scene_id} {index}",
        preview_url=f"memory://clips/{scene_id}/{index}/preview.jpg",
        source_url=f"memory://clips/{scene_id}/{index}",
        duration_seconds=duration_seconds,
        width=1920,
        height=1080,
        selection_reason="first_candidate_for_scene_query",
    )


def test_planner_satisfies_port_and_is_repeatable() -> None:
    planner = DeterministicVideoAssemblyPlanner()
    scenes = (_scene("scene-2"), _scene("scene-10"))
    clips = (_selected_clip("scene-10", 1), _selected_clip("scene-2", 1))

    assert isinstance(planner, VideoAssemblyPlanner)
    assert planner.plan(scenes, clips) == planner.plan(scenes, clips)


def test_scene_table_order_wins_over_lexical_and_clip_order() -> None:
    segments = DeterministicVideoAssemblyPlanner().plan(
        (_scene("scene-2"), _scene("scene-10")),
        (_selected_clip("scene-10", 1), _selected_clip("scene-2", 1)),
    )

    assert [segment.scene_id for segment in segments] == [
        "scene-2",
        "scene-10",
    ]
    assert [segment.order_index for segment in segments] == [0, 1]


def test_multiple_clips_preserve_input_order_and_split_scene_duration() -> None:
    segments = DeterministicVideoAssemblyPlanner().plan(
        (_scene("scene-1", duration_seconds=10.0),),
        (
            _selected_clip("scene-1", 2),
            _selected_clip("scene-1", 1),
            _selected_clip("scene-1", 3),
        ),
    )

    assert [segment.provider_clip_id for segment in segments] == [
        "scene-1-2",
        "scene-1-1",
        "scene-1-3",
    ]
    assert [segment.target_duration_seconds for segment in segments] == [
        pytest.approx(10.0 / 3.0),
        pytest.approx(10.0 / 3.0),
        pytest.approx(10.0 / 3.0),
    ]
    assert sum(segment.target_duration_seconds for segment in segments) == (
        pytest.approx(10.0)
    )


def test_scene_without_clip_is_skipped_and_neighbors_still_emit() -> None:
    segments = DeterministicVideoAssemblyPlanner().plan(
        (_scene("scene-1"), _scene("scene-2"), _scene("scene-3")),
        (_selected_clip("scene-1", 1), _selected_clip("scene-3", 1)),
    )

    assert [segment.scene_id for segment in segments] == ["scene-1", "scene-3"]
    assert [segment.order_index for segment in segments] == [0, 1]


def test_planner_copies_metadata_and_keeps_duration_meanings_distinct() -> None:
    segment = DeterministicVideoAssemblyPlanner().plan(
        (_scene("scene-1", duration_seconds=4.5),),
        (_selected_clip("scene-1", 1, duration_seconds=12.0),),
    )[0]

    assert segment == VideoAssemblySegment(
        scene_id="scene-1",
        query_text="query scene-1 1",
        narration="Narration for scene-1",
        visual_query="Visual query for scene-1",
        provider="stub",
        provider_clip_id="scene-1-1",
        title="Clip scene-1 1",
        preview_url="memory://clips/scene-1/1/preview.jpg",
        source_url="memory://clips/scene-1/1",
        target_duration_seconds=4.5,
        source_duration_seconds=12.0,
        width=1920,
        height=1080,
        order_index=0,
        transition="cut",
        continuity_note="ordered_by_scene_table",
        selection_reason="first_candidate_for_scene_query",
    )


def test_unknown_selected_clip_scene_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown scene IDs: scene-missing"):
        DeterministicVideoAssemblyPlanner().plan(
            (_scene("scene-1"),),
            (_selected_clip("scene-missing", 1),),
        )


@pytest.mark.parametrize(
    ("scenes", "selected_clips"),
    [
        ((), ()),
        ((_scene("scene-1"),), ()),
        ((), (_selected_clip("scene-1", 1),)),
    ],
)
def test_empty_input_produces_empty_segments(
    scenes: tuple[SceneSpec, ...],
    selected_clips: tuple[SelectedClip, ...],
) -> None:
    assert DeterministicVideoAssemblyPlanner().plan(
        scenes, selected_clips
    ) == ()


def test_fake_records_inputs_and_returns_configured_segments() -> None:
    segment = DeterministicVideoAssemblyPlanner().plan(
        (_scene("scene-1"),),
        (_selected_clip("scene-1", 1),),
    )[0]
    fake = FakeVideoAssemblyPlanner((segment,))
    scenes = (_scene("scene-2"),)
    selected_clips = (_selected_clip("scene-2", 1),)

    assert fake.plan(scenes, selected_clips) == (segment,)
    assert fake.calls == [(scenes, selected_clips)]
