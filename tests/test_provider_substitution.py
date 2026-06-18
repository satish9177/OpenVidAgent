from backend.app.domain import AssetKind, RenderSpec
from backend.app.ports import (
    LLMProvider,
    Renderer,
    StockProvider,
    SubtitleBuilder,
    TTSProvider,
)
from tests.fakes import (
    FakeLLMProvider,
    FakeRenderer,
    FakeStockProvider,
    FakeSubtitleBuilder,
    FakeTTSProvider,
)


def test_fake_providers_are_substitutable_through_ports() -> None:
    llm: LLMProvider = FakeLLMProvider()
    stock: StockProvider = FakeStockProvider()
    tts: TTSProvider = FakeTTSProvider()
    subtitles: SubtitleBuilder = FakeSubtitleBuilder()
    renderer: Renderer = FakeRenderer()

    assert isinstance(llm, LLMProvider)
    assert isinstance(stock, StockProvider)
    assert isinstance(tts, TTSProvider)
    assert isinstance(subtitles, SubtitleBuilder)
    assert isinstance(renderer, Renderer)

    script = llm.draft_script("explain local-first video agents")
    scenes = tuple(llm.build_scene_table(script))
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
