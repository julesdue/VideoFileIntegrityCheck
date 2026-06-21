"""
One module per UI check method, each exposing a run(file_path, ffmpeg_path, ffprobe_path,
log_callback, progress_callback) -> (returncode, log_content, errors, stats) entry point.
"""
from . import basic
from . import frame_crc
from . import frame_md5
from . import stream_analysis
from . import sync_check
from . import file_validation
from . import quality_analysis
from . import metadata_validation

CHECK_MODULES = {
    'basic': basic,
    'frame_crc': frame_crc,
    'frame_md5': frame_md5,
    'stream_analysis': stream_analysis,
    'sync_check': sync_check,
    'file_validation': file_validation,
    'quality_analysis': quality_analysis,
    'metadata_validation': metadata_validation,
}

CHECK_DESCRIPTIONS = {
    'basic': 'Basic integrity check using FFmpeg null output',
    'frame_crc': 'Frame-level CRC validation',
    'frame_md5': 'Frame-level MD5 validation',
    'stream_analysis': 'Extended stream analysis with deep probing',
    'sync_check': 'Audio/video synchronization check',
    'file_validation': 'File header, structure, and corruption validation',
    'quality_analysis': 'Video/audio quality analysis (black frames, silence, etc.)',
    'metadata_validation': 'Metadata consistency and timestamp validation',
}
