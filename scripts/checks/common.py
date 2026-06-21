"""Shared types and helpers used by every check module."""
import re
import subprocess
from typing import Dict, List, Optional, Any

# Video file format signatures and validation patterns
VIDEO_SIGNATURES = {
    'mp4': {
        'magic': [b'\x00\x00\x00\x18ftyp', b'\x00\x00\x00\x20ftyp'],
        'extensions': ['.mp4', '.m4v', '.mov'],
        'container_type': 'mp4'
    },
    'avi': {
        'magic': [b'RIFF'],
        'secondary': [b'AVI '],
        'extensions': ['.avi'],
        'container_type': 'avi'
    },
    'mkv': {
        'magic': [b'\x1A\x45\xDF\xA3'],
        'extensions': ['.mkv', '.webm'],
        'container_type': 'matroska'
    },
    'flv': {
        'magic': [b'FLV'],
        'extensions': ['.flv'],
        'container_type': 'flv'
    },
    'wmv': {
        'magic': [b'\x30\x26\xB2\x75\x8E\x66\xCF\x11'],
        'extensions': ['.wmv', '.asf'],
        'container_type': 'asf'
    },
    'ts': {
        'magic': [b'\x47'],
        'extensions': ['.ts', '.m2ts'],
        'container_type': 'mpegts'
    }
}


class VideoIntegrityError:
    """Represents a video integrity issue with severity and details"""
    def __init__(self, error_type: str, severity: str, message: str,
                 location: Optional[str] = None, timestamp: Optional[float] = None,
                 frame_number: Optional[int] = None, additional_info: Optional[Dict] = None):
        self.error_type = error_type
        self.severity = severity  # 'critical', 'major', 'minor', 'warning'
        self.message = message
        self.location = location
        self.timestamp = timestamp
        self.frame_number = frame_number
        self.additional_info = additional_info or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.error_type,
            'severity': self.severity,
            'message': self.message,
            'location': self.location,
            'timestamp': self.timestamp,
            'frame_number': self.frame_number,
            'additional_info': self.additional_info
        }

    def get_detailed_message(self) -> str:
        """Generate a detailed, human-readable error message"""
        # Add application error indicators
        app_error_types = ['ffmpeg_pipeline_error', 'ffmpeg_conversion_error', 'ffmpeg_invalid_args', 'unsupported_codec', 'operation_not_supported']
        is_app_error = self.error_type in app_error_types

        msg = self.message

        # Add prefix to distinguish app vs file errors (without icons for cleaner summary log)
        if is_app_error:
            msg = f"APP ERROR: {msg}"
        else:
            msg = f"FILE ISSUE: {msg}"

        # Add frame information if available
        if self.frame_number is not None:
            msg = f"Frame #{self.frame_number}: {msg}"
        elif self.timestamp is not None:
            minutes = int(self.timestamp // 60)
            seconds = self.timestamp % 60
            msg = f"At {minutes}:{seconds:06.3f}: {msg}"

        # Add additional context
        if self.additional_info:
            details = []
            for key, value in self.additional_info.items():
                if key == 'codec' and value:
                    details.append(f"Codec: {value}")
                elif key == 'stream_index' and value is not None:
                    details.append(f"Stream {value}")
                elif key == 'error_code' and value:
                    details.append(f"Error code: {value}")
                elif key == 'bitrate' and value:
                    details.append(f"Bitrate: {value}")
                elif key == 'resolution' and value:
                    details.append(f"Resolution: {value}")

            if details:
                msg += f" ({', '.join(details)})"

        return msg


def generate_statistics(errors: List[VideoIntegrityError]) -> Dict[str, Any]:
    """Generate summary statistics for a list of detected issues"""
    stats = {
        'total_errors': len(errors),
        'by_severity': {'critical': 0, 'major': 0, 'minor': 0, 'warning': 0},
        'by_category': {}
    }

    for error in errors:
        stats['by_severity'][error.severity] += 1
        category = error.error_type
        stats['by_category'][category] = stats['by_category'].get(category, 0) + 1

    return stats


def parse_detailed_error(log_line: str, file_path: str) -> Optional[VideoIntegrityError]:
    """Parse a single FFmpeg log line for detailed error information"""
    line = log_line.strip()
    line_lower = line.lower()

    timestamp = None
    frame_number = None
    additional_info = {}

    # Common timestamp patterns in FFmpeg output
    time_patterns = [
        r'time=(\d+):(\d+):(\d+\.?\d*)',  # time=00:01:30.123
        r'timestamp:\s*(\d+\.?\d*)',       # timestamp: 30.123
        r'frame\s*=\s*(\d+)',              # frame= 1234
        r'frame:\s*(\d+)'                  # frame: 1234
    ]

    for pattern in time_patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            if len(match.groups()) == 3:  # HH:MM:SS format
                h, m, s = match.groups()
                timestamp = int(h) * 3600 + int(m) * 60 + float(s)
            elif 'frame' in pattern.lower():
                frame_number = int(match.group(1))
            else:
                timestamp = float(match.group(1))
            break

    # Extract codec information
    codec_match = re.search(r'codec[:\s]+([^\s,]+)', line, re.IGNORECASE)
    if codec_match:
        additional_info['codec'] = codec_match.group(1)

    # Extract stream information
    stream_match = re.search(r'stream[:\s]+(\d+)', line, re.IGNORECASE)
    if stream_match:
        additional_info['stream_index'] = int(stream_match.group(1))

    # Extract error codes
    error_code_match = re.search(r'error[:\s]+(-?\d+)', line, re.IGNORECASE)
    if error_code_match:
        additional_info['error_code'] = error_code_match.group(1)

    # Detailed error pattern matching with specific messages
    error_patterns = [
        # Application/FFmpeg errors (not file corruption)
        (r'error sending frames to consumer', 'ffmpeg_pipeline_error', 'minor', 'FFmpeg pipeline error - method may be incompatible with this file'),
        (r'conversion failed', 'ffmpeg_conversion_error', 'minor', 'FFmpeg conversion failed - try different check method'),
        (r'task finished with error code.*(-22|22)', 'ffmpeg_invalid_args', 'minor', 'FFmpeg invalid arguments - file format may not support this operation'),
        (r'unsupported.*codec', 'unsupported_codec', 'warning', 'Codec not fully supported by FFmpeg build'),
        (r'operation not supported', 'operation_not_supported', 'warning', 'Operation not supported for this file format'),

        # Frame-specific errors (actual corruption)
        (r'error.*frame.*(\d+)', 'frame_error', 'major', 'Frame decoding error'),
        (r'concealing.*errors.*frame.*(\d+)', 'frame_concealment', 'minor', 'Frame error concealment applied'),
        (r'missing.*reference.*frame.*(\d+)', 'missing_reference', 'major', 'Missing reference frame'),
        (r'invalid.*frame.*(\d+)', 'invalid_frame', 'major', 'Invalid frame data'),
        (r'corrupt.*frame.*(\d+)', 'corrupt_frame', 'major', 'Corrupted frame detected'),

        # Bitstream errors
        (r'invalid.*bitstream', 'bitstream_invalid', 'major', 'Invalid bitstream syntax'),
        (r'truncated.*bitstream', 'bitstream_truncated', 'major', 'Truncated bitstream data'),
        (r'bitstream.*error', 'bitstream_error', 'major', 'Bitstream parsing error'),

        # Decoder errors
        (r'decoder.*error.*(\d+)', 'decoder_error', 'major', 'Video decoder error'),
        (r'decoding.*failed', 'decode_failed', 'major', 'Frame decoding failed'),
        (r'decode.*error', 'decode_error', 'major', 'Decoding error occurred'),

        # Audio errors
        (r'audio.*decode.*error', 'audio_decode_error', 'major', 'Audio decoding error'),
        (r'audio.*frame.*error', 'audio_frame_error', 'major', 'Audio frame error'),

        # Container/format errors
        (r'invalid.*data.*found', 'invalid_data', 'major', 'Invalid data in stream'),
        (r'end of file.*unexpected', 'unexpected_eof', 'critical', 'Unexpected end of file'),
        (r'header.*missing', 'missing_header', 'critical', 'Missing file header'),
        (r'invalid.*header', 'invalid_header', 'major', 'Invalid file header'),

        # Sync and timing errors
        (r'pts.*dts.*inconsistent', 'pts_dts_error', 'minor', 'PTS/DTS timestamp inconsistency'),
        (r'discontinuous.*timestamp', 'timestamp_discontinuous', 'minor', 'Timestamp discontinuity detected'),

        # Quality issues
        (r'frame.*dropped', 'frame_dropped', 'warning', 'Frame dropped during processing'),
        (r'duplicate.*frame', 'duplicate_frame', 'warning', 'Duplicate frame detected'),
    ]

    for pattern, error_type, severity, base_message in error_patterns:
        match = re.search(pattern, line_lower)
        if match:
            if match.groups():
                try:
                    extracted_frame = int(match.group(1))
                    if frame_number is None:
                        frame_number = extracted_frame
                except (ValueError, IndexError):
                    pass

            if 'frame' in base_message.lower() and frame_number:
                detailed_message = f"{base_message} (frame #{frame_number})"
            elif timestamp:
                minutes = int(timestamp // 60)
                seconds = timestamp % 60
                detailed_message = f"{base_message} at {minutes}:{seconds:06.3f}"
            else:
                detailed_message = f"{base_message}: {line}"

            return VideoIntegrityError(
                error_type=error_type,
                severity=severity,
                message=detailed_message,
                location=file_path,
                timestamp=timestamp,
                frame_number=frame_number,
                additional_info=additional_info
            )

    # Generic error fallback
    if any(keyword in line_lower for keyword in ['error', 'failed', 'invalid', 'corrupt', 'missing']):
        severity = 'major'
        if any(critical in line_lower for critical in ['critical', 'fatal', 'abort']):
            severity = 'critical'
        elif any(minor in line_lower for minor in ['warning', 'concealing']):
            severity = 'minor'

        return VideoIntegrityError(
            error_type='generic_error',
            severity=severity,
            message=f"Generic error: {line}",
            location=file_path,
            timestamp=timestamp,
            frame_number=frame_number,
            additional_info=additional_info
        )

    return None


def format_check_result(errors: List[VideoIntegrityError], log_callback=None, progress_callback=None):
    """
    Shared formatting for the "new style" check modules (file_validation, quality_analysis,
    metadata_validation): turns a list of VideoIntegrityError into the
    (returncode, log_content, errors, stats) tuple expected by the UI.
    """
    stats = generate_statistics(errors)

    log_lines = []
    for error in errors:
        severity_tag = f"[{error.severity.upper()}]"
        detailed_msg = error.get_detailed_message()
        log_line = f"{severity_tag} {error.error_type}: {detailed_msg}"
        log_lines.append(log_line)
        if log_callback:
            log_callback(log_line)

    summary = f"\nSUMMARY: {stats['total_errors']} issues found"
    if stats['total_errors'] > 0:
        severity_counts = ", ".join([
            f"{count} {sev}"
            for sev, count in stats['by_severity'].items()
            if count > 0
        ])
        summary += f" ({severity_counts})"
    log_lines.append(summary)
    if log_callback:
        log_callback(summary)

    returncode = 0
    if stats['by_severity']['critical'] > 0:
        returncode = 2
    elif stats['by_severity']['major'] > 0:
        returncode = 1

    if progress_callback:
        progress_callback(100)

    return returncode, '\n'.join(log_lines), errors, stats


def run_ffmpeg_stream(ffmpeg_path: str, file: str, extra_args: List[str], log_callback=None, progress_callback=None):
    """
    Shared runner for the "legacy" FFmpeg-subprocess check modules (basic, frame_crc,
    frame_md5, stream_analysis, sync_check): streams FFmpeg's combined stdout/stderr to
    log_callback line by line and reports percent-complete via progress_callback using
    the file's known duration.

    Returns (returncode, log_content, errors, stats) - errors/stats are always empty since
    these legacy methods only return a raw FFmpeg log, not structured errors.
    """
    duration = None
    probe_cmd = [
        ffmpeg_path,
        '-v', 'warning',
        '-select_streams', 'v:0',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-i', file
    ]
    try:
        result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', shell=False)
        duration = float(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:
        duration = None

    cmd = [ffmpeg_path] + extra_args

    log_lines = []
    time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.?\d*)')
    try:
        # Use UTF-8 encoding to avoid UnicodeDecodeError on Windows
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', shell=False)
        if process.stdout:
            for line in process.stdout:
                log_lines.append(line)
                if log_callback:
                    log_callback(line.rstrip())
                if progress_callback and duration:
                    match = time_pattern.search(line)
                    if match:
                        h, m, s = match.groups()
                        current_sec = int(h) * 3600 + int(m) * 60 + float(s)
                        percent = min(int((current_sec / duration) * 100), 100)
                        progress_callback(percent)
        process.wait()
        log_content = ''.join(log_lines)
        if progress_callback and duration:
            progress_callback(100)
        return process.returncode, log_content, [], {}
    except Exception as e:
        if log_callback:
            log_callback(str(e))
        if progress_callback:
            progress_callback(100)
        return -1, str(e), [], {}
