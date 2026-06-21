"""Extended stream analysis with deep probing (the 'Stream Analysis' checkbox)."""
from .common import run_ffmpeg_stream


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    extra_args = [
        '-v', 'info', '-analyzeduration', '2147483647', '-probesize', '2147483647',
        '-i', file_path, '-f', 'null', '-'
    ]
    return run_ffmpeg_stream(ffmpeg_path, file_path, extra_args, log_callback, progress_callback)
