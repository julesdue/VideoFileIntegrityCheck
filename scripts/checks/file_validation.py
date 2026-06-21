"""File header, container structure, and corruption validation (the 'File Validation' checkbox)."""
import struct
import subprocess
import json
from pathlib import Path
from typing import List

from .common import VideoIntegrityError, VIDEO_SIGNATURES, generate_statistics, format_check_result


def validate_file_header(file_path: str) -> List[VideoIntegrityError]:
    """Validate video file header and container format"""
    errors = []

    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)

        if len(header) < 8:
            errors.append(VideoIntegrityError(
                'file_header', 'critical',
                f'File too small ({len(header)} bytes)', file_path
            ))
            return errors

        # Check file signature
        format_detected = None
        for fmt, info in VIDEO_SIGNATURES.items():
            for magic in info['magic']:
                if header.startswith(magic):
                    format_detected = fmt
                    break
            if format_detected:
                break

        if not format_detected:
            # Check for secondary signatures
            for fmt, info in VIDEO_SIGNATURES.items():
                if 'secondary' in info:
                    for secondary in info['secondary']:
                        if secondary in header[:16]:
                            format_detected = fmt
                            break

        if not format_detected:
            errors.append(VideoIntegrityError(
                'file_header', 'major',
                f'Unrecognized or corrupted file signature: {header[:16].hex()}',
                file_path
            ))
        else:
            # Validate file extension matches detected format
            file_ext = Path(file_path).suffix.lower()
            if file_ext not in VIDEO_SIGNATURES[format_detected]['extensions']:
                errors.append(VideoIntegrityError(
                    'file_header', 'minor',
                    f'Extension {file_ext} doesn\'t match detected format {format_detected}',
                    file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'file_header', 'critical',
            f'Cannot read file header: {str(e)}', file_path
        ))

    return errors


def validate_file_structure(file_path: str) -> List[VideoIntegrityError]:
    """Validate container-specific file structure"""
    errors = []

    try:
        file_ext = Path(file_path).suffix.lower()

        if file_ext in ['.mp4', '.m4v', '.mov']:
            errors.extend(_validate_mp4_structure(file_path))
        elif file_ext in ['.avi']:
            errors.extend(_validate_avi_structure(file_path))
        elif file_ext in ['.mkv', '.webm']:
            errors.extend(_validate_matroska_structure(file_path))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'file_structure', 'major',
            f'Structure validation failed: {str(e)}', file_path
        ))

    return errors


def _validate_mp4_structure(file_path: str) -> List[VideoIntegrityError]:
    """Validate MP4/MOV container structure by walking top-level atoms (boxes)"""
    errors = []

    try:
        file_size = Path(file_path).stat().st_size
        with open(file_path, 'rb') as f:
            found_moov = False
            found_mdat = False

            while True:
                atom_start = f.tell()
                atom_header = f.read(8)
                if len(atom_header) < 8:
                    break

                atom_size, atom_type = struct.unpack('>I4s', atom_header)

                if atom_size == 1:
                    # Extended size: real size is in the next 8 bytes (64-bit)
                    ext_size_bytes = f.read(8)
                    if len(ext_size_bytes) < 8:
                        errors.append(VideoIntegrityError(
                            'mp4_structure', 'major',
                            f'Truncated 64-bit size field for atom {atom_type!r} at offset {atom_start}',
                            file_path
                        ))
                        break
                    atom_size = struct.unpack('>Q', ext_size_bytes)[0]
                elif atom_size == 0:
                    # Atom extends to end of file (valid only for the last atom)
                    atom_size = file_size - atom_start
                elif 0 < atom_size < 8:
                    errors.append(VideoIntegrityError(
                        'mp4_structure', 'major',
                        f'Invalid atom size {atom_size} for {atom_type!r} at offset {atom_start} (must be >= 8)',
                        file_path
                    ))
                    break

                if atom_type == b'moov':
                    found_moov = True
                elif atom_type == b'mdat':
                    found_mdat = True

                atom_end = atom_start + atom_size
                if atom_end > file_size:
                    errors.append(VideoIntegrityError(
                        'mp4_structure', 'critical',
                        f'Atom {atom_type!r} at offset {atom_start} claims size {atom_size}, '
                        f'exceeding file size {file_size} (truncated or corrupted file)',
                        file_path
                    ))
                    break

                if atom_end == atom_start:
                    # Shouldn't happen given the checks above, but avoid an infinite loop
                    break

                f.seek(atom_end)

            if not found_moov:
                errors.append(VideoIntegrityError(
                    'mp4_structure', 'critical',
                    'Missing moov atom (movie metadata)', file_path
                ))

            if not found_mdat:
                errors.append(VideoIntegrityError(
                    'mp4_structure', 'critical',
                    'Missing mdat atom (media data)', file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'mp4_structure', 'major',
            f'MP4 structure validation error: {str(e)}', file_path
        ))

    return errors


def _validate_avi_structure(file_path: str) -> List[VideoIntegrityError]:
    """Validate AVI container structure"""
    errors = []

    try:
        with open(file_path, 'rb') as f:
            # Read RIFF header
            riff_header = f.read(12)
            if len(riff_header) < 12:
                errors.append(VideoIntegrityError(
                    'avi_structure', 'critical',
                    'Incomplete RIFF header', file_path
                ))
                return errors

            magic, file_size, format_type = struct.unpack('<4sI4s', riff_header)

            if magic != b'RIFF':
                errors.append(VideoIntegrityError(
                    'avi_structure', 'critical',
                    'Invalid RIFF signature', file_path
                ))

            if format_type != b'AVI ':
                errors.append(VideoIntegrityError(
                    'avi_structure', 'critical',
                    f'Invalid AVI format type: {format_type}', file_path
                ))

            # Verify file size
            actual_size = Path(file_path).stat().st_size
            if abs(actual_size - (file_size + 8)) > 1024:  # Allow 1KB tolerance
                errors.append(VideoIntegrityError(
                    'avi_structure', 'major',
                    f'File size mismatch: header says {file_size + 8}, actual {actual_size}',
                    file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'avi_structure', 'major',
            f'AVI structure validation error: {str(e)}', file_path
        ))

    return errors


def _validate_matroska_structure(file_path: str) -> List[VideoIntegrityError]:
    """Validate Matroska/WebM container structure"""
    errors = []

    try:
        with open(file_path, 'rb') as f:
            # Check EBML header
            ebml_header = f.read(4)
            if ebml_header != b'\x1A\x45\xDF\xA3':
                errors.append(VideoIntegrityError(
                    'matroska_structure', 'critical',
                    'Invalid EBML header signature', file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'matroska_structure', 'major',
            f'Matroska structure validation error: {str(e)}', file_path
        ))

    return errors


def check_file_corruption(file_path: str) -> List[VideoIntegrityError]:
    """Check for general file corruption indicators"""
    errors = []

    try:
        file_stat = Path(file_path).stat()

        # Check for zero-byte file
        if file_stat.st_size == 0:
            errors.append(VideoIntegrityError(
                'file_corruption', 'critical',
                'File is empty (0 bytes)', file_path
            ))
            return errors

        # Check for suspiciously small files
        if file_stat.st_size < 1024:
            errors.append(VideoIntegrityError(
                'file_corruption', 'major',
                f'File suspiciously small ({file_stat.st_size} bytes)', file_path
            ))

        # Spot check file for null bytes patterns (potential corruption)
        with open(file_path, 'rb') as f:
            chunk_size = 64 * 1024
            chunks_checked = 0
            null_chunks = 0

            while chunks_checked < 10:  # Check first 10 chunks
                chunk = f.read(chunk_size)
                if not chunk:
                    break

                # Check for chunks that are mostly null bytes
                null_count = chunk.count(b'\x00')
                if null_count > chunk_size * 0.9:  # 90% null bytes
                    null_chunks += 1

                chunks_checked += 1

            if null_chunks > chunks_checked * 0.3:  # 30% of chunks are mostly null
                errors.append(VideoIntegrityError(
                    'file_corruption', 'major',
                    f'High null byte density detected ({null_chunks}/{chunks_checked} chunks)',
                    file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'file_corruption', 'major',
            f'Corruption check failed: {str(e)}', file_path
        ))

    return errors


def external_tool_analysis(file_path: str) -> List[VideoIntegrityError]:
    """Analysis using external tools (MediaInfo, etc.)"""
    errors = []
    errors.extend(_mediainfo_analysis(file_path))
    return errors


def _mediainfo_analysis(file_path: str) -> List[VideoIntegrityError]:
    """Analyze using MediaInfo if available"""
    errors = []

    try:
        # Try to find MediaInfo
        mediainfo_paths = [
            'mediainfo',
            'MediaInfo.exe',
            'C:\\Program Files\\MediaInfo\\MediaInfo.exe',
            'C:\\Program Files (x86)\\MediaInfo\\MediaInfo.exe'
        ]

        mediainfo_path = None
        for path in mediainfo_paths:
            try:
                result = subprocess.run([path, '--Version'],
                                        capture_output=True, text=True, encoding='utf-8', timeout=5)
                if result.returncode == 0:
                    mediainfo_path = path
                    break
            except Exception:
                continue

        if not mediainfo_path:
            errors.append(VideoIntegrityError(
                'external_tools', 'minor',
                'MediaInfo not found - install for enhanced analysis', file_path
            ))
            return errors

        # Run MediaInfo analysis
        cmd = [mediainfo_path, '--Output=JSON', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)

                # Extract useful information from MediaInfo
                media_info = data.get('media', {})
                tracks = media_info.get('track', [])

                for track in tracks:
                    track_type = track.get('@type', '').lower()

                    # Check for encoding errors reported by MediaInfo
                    if 'error' in str(track).lower():
                        errors.append(VideoIntegrityError(
                            'mediainfo_analysis', 'major',
                            f'MediaInfo detected issues in {track_type} track',
                            file_path
                        ))

                    # Check for missing essential properties
                    if track_type == 'video':
                        if not track.get('Width') or not track.get('Height'):
                            errors.append(VideoIntegrityError(
                                'mediainfo_analysis', 'warning',
                                'Video dimensions not detected by MediaInfo', file_path
                            ))

            except json.JSONDecodeError:
                errors.append(VideoIntegrityError(
                    'mediainfo_analysis', 'minor',
                    'Failed to parse MediaInfo JSON output', file_path
                ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'mediainfo_analysis', 'warning',
            'MediaInfo analysis timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'mediainfo_analysis', 'minor',
            f'MediaInfo analysis error: {str(e)}', file_path
        ))

    return errors


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    """Entry point used by the 'file_validation' UI checkbox"""
    errors = []
    errors.extend(validate_file_header(file_path))
    errors.extend(validate_file_structure(file_path))
    errors.extend(check_file_corruption(file_path))
    errors.extend(external_tool_analysis(file_path))
    return format_check_result(errors, log_callback, progress_callback)
