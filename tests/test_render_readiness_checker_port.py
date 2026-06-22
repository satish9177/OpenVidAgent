from collections.abc import Sequence
from typing import get_type_hints

from backend.app.domain import (
    RenderPlanSegment,
    RenderReadinessReport,
    RenderOutputManifest,
)
from backend.app.ports import (
    FfmpegAvailabilityProbe,
    Renderer,
    RenderOutputGenerator,
    RenderReadinessChecker,
)


class StructuralChecker:
    def check(
        self,
        render_plan_asset_id: str,
        render_plan_version: int,
        render_plan_segments: Sequence[RenderPlanSegment],
        render_output: RenderOutputManifest | None,
        ffmpeg_availability: str,
    ) -> RenderReadinessReport:
        raise NotImplementedError


class StructuralProbe:
    def check(self) -> str:
        return "not_checked"


def test_structural_fakes_satisfy_readiness_ports() -> None:
    assert isinstance(StructuralChecker(), RenderReadinessChecker)
    assert isinstance(StructuralProbe(), FfmpegAvailabilityProbe)


def test_render_readiness_ports_live_in_provider_module() -> None:
    assert RenderReadinessChecker.__module__ == "backend.app.ports.providers"
    assert FfmpegAvailabilityProbe.__module__ == "backend.app.ports.providers"


def test_render_readiness_checker_has_exact_safe_type_hints() -> None:
    hints = get_type_hints(RenderReadinessChecker.check)

    assert hints == {
        "render_plan_asset_id": str,
        "render_plan_version": int,
        "render_plan_segments": Sequence[RenderPlanSegment],
        "render_output": RenderOutputManifest | None,
        "ffmpeg_availability": str,
        "return": RenderReadinessReport,
    }
    assert get_type_hints(FfmpegAvailabilityProbe.check) == {"return": str}


def test_render_readiness_checker_is_distinct_from_render_ports() -> None:
    assert RenderReadinessChecker is not Renderer
    assert RenderReadinessChecker is not RenderOutputGenerator
    assert FfmpegAvailabilityProbe is not Renderer
