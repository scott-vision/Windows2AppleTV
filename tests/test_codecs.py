import numpy
import pytest

from pycast.capture.models import CapturedAudioChunk, CapturedVideoFrame
from pycast.codecs.alac import AlacAudioEncoder
from pycast.codecs.h264 import H264VideoEncoder


def test_h264_encodes_and_flushes_packet() -> None:
    encoder = H264VideoEncoder(64, 48, 30)
    frame = numpy.zeros((48, 64, 3), dtype=numpy.uint8)
    packets = encoder.encode(CapturedVideoFrame(frame, 1_000_000_000, 0))
    packets += encoder.flush()
    assert packets
    assert any(packet.keyframe for packet in packets)
    assert all(packet.data for packet in packets)
    assert all(packet.timestamp_ns >= 0 for packet in packets)


def test_alac_encodes_pcm() -> None:
    encoder = AlacAudioEncoder(48_000, 2)
    pcm = numpy.zeros((256, 2), dtype=numpy.int16).tobytes()
    chunk = CapturedAudioChunk(pcm, 2_000_000_000, 48_000, 2, 2, 256)
    packets = encoder.encode(chunk)
    packets += encoder.flush()
    assert packets
    assert all(packet.data for packet in packets)
    assert all(packet.sample_rate == 48_000 for packet in packets)


def test_audio_metadata_mismatch_is_rejected() -> None:
    encoder = AlacAudioEncoder(48_000, 2)
    with pytest.raises(ValueError, match="byte length"):
        encoder.encode(CapturedAudioChunk(b"\0", 0, 48_000, 2, 2, 256))
