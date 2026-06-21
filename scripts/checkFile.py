"""
Dispatches a check method (one of get_available_check_methods()) to its module under
scripts/checks/. Each UI checkbox maps 1:1 to a module in scripts/checks/ - see that
package for the actual check implementations.
"""
from .checks import CHECK_MODULES, CHECK_DESCRIPTIONS
from .checks.common import VideoIntegrityError  # re-exported for backward compatibility


def check_video_file(file, ffmpeg_path, check_method='basic', ffprobe_path=None, log_callback=None, progress_callback=None):
    """
    Run a single check method against a video file.

    Returns tuple: (returncode, log_content, detailed_errors, statistics)
    See get_available_check_methods() for the list of valid check_method values.
    If ffprobe_path is omitted, it's derived from ffmpeg_path (only reliable when
    ffmpeg_path's directory doesn't itself contain the substring "ffmpeg").
    """
    module = CHECK_MODULES.get(check_method)
    if module is None:
        raise ValueError(f"Unknown check method: {check_method!r}")

    if ffprobe_path is None:
        ffprobe_path = ffmpeg_path.replace('ffmpeg', 'ffprobe')
    return module.run(file, ffmpeg_path, ffprobe_path, log_callback=log_callback, progress_callback=progress_callback)


def get_available_check_methods():
    """Get list of all available check methods with descriptions"""
    return dict(CHECK_DESCRIPTIONS)
