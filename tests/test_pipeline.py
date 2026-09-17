from pathlib import Path

import av
import numpy

from pycast.capture.models import CapturedAudioChunk, CapturedVideoFrame
from pycast.pipeline.diagnostic import DiagnosticPipeline


def test_pipeline_orders_media_by_shared_timestamp(tmp_path: Path) -> None:
    frames = [
        CapturedVideoFrame(numpy.zeros((48, 64, 3), dtype=numpy.uint8), 1_000_000_000, 0),
        CapturedVideoFrame(numpy.full((48, 64, 3), 20, dtype=numpy.uint8), 1_033_000_000, 0),
    ]
    pcm = numpy.zeros((1024, 2), dtype=numpy.int16).tobytes()
    audio = [CapturedAudioChunk(pcm, 1_010_000_000, 48_000, 2, 2, 1024)]
    output = tmp_path / "diagnostic.mkv"

    result = DiagnosticPipeline(64, 48, 30, 48_000).encode_to_file(frames, audio, output)

    assert output.exists()
    assert result.video_frames == 2
    assert result.audio_chunks == 1
    assert result.video_packets >= 1
    assert result.audio_packets >= 1
    with av.open(str(output)) as container:
        assert {stream.codec_context.name for stream in container.streams} == {"h264", "alac"}
