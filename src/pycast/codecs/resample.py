"""PCM normalization helpers for the local and future streaming pipelines."""

from typing import Any

from pycast.capture.models import CapturedAudioChunk


def normalize_pcm(chunk: CapturedAudioChunk, target_rate: int, target_channels: int = 2) -> CapturedAudioChunk:
    """Convert signed 16-bit PCM to the requested rate and mono/stereo layout."""
    if chunk.sample_width != 2:
        raise ValueError("only 16-bit PCM is supported")
    if target_rate <= 0 or target_channels not in (1, 2):
        raise ValueError("target_rate must be positive and target_channels must be 1 or 2")
    if chunk.sample_rate == target_rate and chunk.channels == target_channels:
        return chunk
    try:
        import av
        import numpy
    except ImportError as exc:
        raise RuntimeError("PyAV and NumPy are required for PCM normalization") from exc
    samples: Any = numpy.frombuffer(chunk.data, dtype=numpy.int16).reshape(chunk.frame_count, chunk.channels).T.copy()
    frame = av.AudioFrame.from_ndarray(samples, format="s16p", layout="mono" if chunk.channels == 1 else "stereo")
    frame.sample_rate = chunk.sample_rate
    resampler = av.audio.resampler.AudioResampler(format="s16p", layout="mono" if target_channels == 1 else "stereo", rate=target_rate)
    converted = resampler.resample(frame)
    if not converted:
        return CapturedAudioChunk(b"", chunk.timestamp_ns, target_rate, target_channels, 2, 0)
    result = converted[0]
    data = result.to_ndarray().T.astype(numpy.int16, copy=False).tobytes()
    return CapturedAudioChunk(data, chunk.timestamp_ns, target_rate, target_channels, 2, result.samples)
