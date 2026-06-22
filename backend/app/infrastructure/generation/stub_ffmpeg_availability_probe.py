"""FFmpeg availability stub that performs no binary discovery."""

from backend.app.ports import FfmpegAvailabilityProbe


class StubFfmpegAvailabilityProbe(FfmpegAvailabilityProbe):
    def check(self) -> str:
        return "not_checked"
