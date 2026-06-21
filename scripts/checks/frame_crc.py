"""Frame-level CRC validation (the 'Frame Crc' checkbox)."""
from .common import run_ffmpeg_stream


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    extra_args = ['-v', 'info', '-i', file_path, '-f', 'framemd5', '-hash', 'crc', '-']
    return run_ffmpeg_stream(ffmpeg_path, file_path, extra_args, log_callback, progress_callback)
