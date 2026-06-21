"""Basic integrity check using FFmpeg null output (the 'Basic' checkbox)."""
from .common import run_ffmpeg_stream


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    extra_args = ['-v', 'info', '-ignore_chapters', '1', '-i', file_path, '-f', 'null', '-']
    return run_ffmpeg_stream(ffmpeg_path, file_path, extra_args, log_callback, progress_callback)
