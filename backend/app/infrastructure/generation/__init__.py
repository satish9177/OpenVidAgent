"""Deterministic local generation adapters (no external calls)."""

from backend.app.infrastructure.generation.deterministic_clip_selector import (
    DeterministicClipSelector,
)
from backend.app.infrastructure.generation.deterministic_video_assembly_planner import (
    DeterministicVideoAssemblyPlanner,
)
from backend.app.infrastructure.generation.echo_script_draft_generator import (
    EchoScriptDraftGenerator,
)
from backend.app.infrastructure.generation.stub_scene_table_planner import (
    StubSceneTablePlanner,
)
from backend.app.infrastructure.generation.stub_render_planner import (
    StubRenderPlanner,
)
from backend.app.infrastructure.generation.stub_render_output_generator import (
    StubRenderOutputGenerator,
)
from backend.app.infrastructure.generation.stub_stock_clip_planner import (
    StubStockClipPlanner,
)
from backend.app.infrastructure.generation.stub_subtitle_composer import (
    StubSubtitleComposer,
)
from backend.app.infrastructure.generation.stub_voiceover_generator import (
    StubVoiceoverGenerator,
)
from backend.app.infrastructure.generation.stub_clip_retrieval_provider import (
    StubClipRetrievalProvider,
)
from backend.app.infrastructure.generation.stub_clip_downloader import (
    StubClipDownloader,
)

__all__ = [
    "DeterministicClipSelector",
    "DeterministicVideoAssemblyPlanner",
    "EchoScriptDraftGenerator",
    "StubClipRetrievalProvider",
    "StubClipDownloader",
    "StubSceneTablePlanner",
    "StubRenderPlanner",
    "StubRenderOutputGenerator",
    "StubStockClipPlanner",
    "StubSubtitleComposer",
    "StubVoiceoverGenerator",
]
