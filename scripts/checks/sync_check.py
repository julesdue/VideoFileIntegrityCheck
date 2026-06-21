"""Audio/video synchronization check (the 'Sync Check' checkbox)."""
from .common import run_ffmpeg_stream


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    extra_args = ['-v', 'info', '-i', file_path, '-vf', r'select=eq(pict_type\,I)', '-vsync', '0', '-f', 'null', '-']
    return run_ffmpeg_stream(ffmpeg_path, file_path, extra_args, log_callback, progress_callback)
