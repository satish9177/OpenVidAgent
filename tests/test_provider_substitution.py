from backend.app.domain import AssetKind, RenderSpec
from backend.app.ports import (
    Renderer,
    SceneTablePlanner,
    ScriptDraftGenerator,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)
from tests.fakes import (
    FakeRenderer,
    FakeSceneTablePlanner,
    FakeScriptDraftGenerator,
    FakeStockProvider,
    FakeSubtitleBuilder,
    FakeTTSProvider,
)


def test_fake_providers_are_substitutable_through_ports() -> None:
    script_generator: ScriptDraftGenerator = FakeScriptDraftGenerator()
    scene_planner: SceneTablePlanner = FakeSceneTablePlanner()
    stock: StockProvider = FakeStockProvider()
    tts: TTSProvider = FakeTTSProvider()
    subtitles: SubtitleBuilder = FakeSubtitleBuilder()
    renderer: Renderer = FakeRenderer()

    assert isinstance(script_generator, ScriptDraftGenerator)
    assert isinstance(scene_planner, SceneTablePlanner)
    assert isinstance(stock, StockProvider)
    assert isinstance(tts, TTSProvider)
    assert isinstance(subtitles, SubtitleBuilder)
    assert isinstance(renderer, Renderer)

    script = script_generator.generate("explain local-first video agents", "en")
    scenes = tuple(scene_planner.plan(script, "en"))
    clips = tuple(stock.find_clips(scenes[0]))
    voice = tts.synthesize(script)
    subtitle_asset = subtitles.build(script, voice)
    render = renderer.render(
        RenderSpec(
            run_id="run-1",
            scenes=scenes,
            clips=clips,
            voice=voice,
            subtitles=subtitle_asset,
        )
    )

    assert clips[0].kind is AssetKind.STOCK_CLIP
    assert voice.kind is AssetKind.VOICE
    assert subtitle_asset.kind is AssetKind.SUBTITLE
    assert render.kind is AssetKind.RENDER
