"""
Metadata consistency, timestamp validation, and FFmpeg-based bitstream/sync analysis
(the 'Metadata Validation' checkbox).

GOP structure, bitstream, frame-integrity, and A/V-sync analysis don't have their own
UI checkbox (they were previously only reachable via the removed 'comprehensive' method),
so they're grouped here alongside metadata/timestamp checks since they rely on the same
ffprobe/ffmpeg stream inspection.
"""
import subprocess
import re
import json
from pathlib import Path
from typing import List

from .common import VideoIntegrityError, parse_detailed_error, format_check_result


def _analyze_gop_structure(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Analyze GOP (Group of Pictures) structure"""
    errors = []

    try:
        cmd = [
            ffprobe_path, '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pict_type,coded_picture_number',
            '-of', 'csv=p=0', file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0:
            errors.append(VideoIntegrityError(
                'gop_analysis', 'major',
                f'GOP analysis failed: {result.stderr}', file_path
            ))
            return errors

        frames = result.stdout.strip().split('\n')
        i_frames = 0
        p_frames = 0
        b_frames = 0

        for frame in frames[:100]:  # Check first 100 frames
            if frame:
                parts = frame.split(',')
                if len(parts) >= 2:
                    pict_type = parts[0]
                    if pict_type == 'I':
                        i_frames += 1
                    elif pict_type == 'P':
                        p_frames += 1
                    elif pict_type == 'B':
                        b_frames += 1

        total_frames = i_frames + p_frames + b_frames
        if total_frames > 0:
            if i_frames == 0:
                errors.append(VideoIntegrityError(
                    'gop_analysis', 'major',
                    'No I-frames detected in first 100 frames', file_path
                ))
            elif i_frames / total_frames > 0.5:
                errors.append(VideoIntegrityError(
                    'gop_analysis', 'warning',
                    f'High I-frame ratio: {i_frames}/{total_frames} ({i_frames/total_frames:.2%})',
                    file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'gop_analysis', 'major',
            f'GOP analysis error: {str(e)}', file_path
        ))

    return errors


def _validate_bitstream(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Validate video bitstream syntax with detailed error reporting"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-v', 'info',
            '-i', file_path,
            '-f', 'null', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

        stderr_lines = result.stderr.split('\n')
        frame_errors = {}

        for line in stderr_lines:
            line = line.strip()
            if not line:
                continue

            detailed_error = parse_detailed_error(line, file_path)
            if detailed_error:
                errors.append(detailed_error)

                if detailed_error.frame_number:
                    frame_errors.setdefault(detailed_error.frame_number, []).append(detailed_error.error_type)

        if len(frame_errors) > 10:
            frame_list = sorted(frame_errors.keys())
            error_summary = f"Multiple frame errors detected across {len(frame_errors)} frames"
            error_summary += f" (frames {frame_list[0]}-{frame_list[-1]})"

            errors.append(VideoIntegrityError(
                'multiple_frame_errors', 'major', error_summary, file_path,
                additional_info={'affected_frames': len(frame_errors)}
            ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'bitstream_validation', 'major',
            f'Bitstream validation failed: {str(e)}', file_path
        ))

    return errors


def _check_frame_integrity(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Check individual frame integrity with detailed frame information"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-v', 'info',
            '-i', file_path,
            '-f', 'framemd5', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=60)

        if result.returncode != 0:
            frame_count = 0
            corrupt_frames = []

            for line in result.stderr.split('\n'):
                if not line.strip():
                    continue

                detailed_error = parse_detailed_error(line, file_path)
                if detailed_error:
                    errors.append(detailed_error)

                    if detailed_error.frame_number:
                        corrupt_frames.append(detailed_error.frame_number)

                if 'frame=' in line:
                    frame_match = re.search(r'frame=\s*(\d+)', line)
                    if frame_match:
                        frame_count = max(frame_count, int(frame_match.group(1)))

            if not errors:
                errors.append(VideoIntegrityError(
                    'frame_integrity', 'major',
                    f'Frame integrity check failed after processing {frame_count} frames: {result.stderr}',
                    file_path,
                    additional_info={'frames_processed': frame_count}
                ))
            elif corrupt_frames:
                if len(corrupt_frames) > 5:
                    summary = f"Frame integrity issues detected in {len(corrupt_frames)} frames"
                    summary += f" (including frames {min(corrupt_frames)}-{max(corrupt_frames)})"
                else:
                    summary = f"Frame integrity issues in frames: {', '.join(map(str, corrupt_frames))}"

                errors.append(VideoIntegrityError(
                    'frame_integrity_summary', 'major', summary, file_path,
                    additional_info={'corrupt_frame_count': len(corrupt_frames)}
                ))
        else:
            frame_lines = [line for line in result.stdout.split('\n') if line.strip()]
            if len(frame_lines) < 10:  # Very few frames
                errors.append(VideoIntegrityError(
                    'frame_integrity', 'warning',
                    f'Very few frames processed: only {len(frame_lines)} frames validated',
                    file_path,
                    additional_info={'frames_validated': len(frame_lines)}
                ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'frame_integrity', 'warning',
            'Frame integrity check timed out (file may be very large or corrupted)', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'frame_integrity', 'major',
            f'Frame integrity check error: {str(e)}', file_path
        ))

    return errors


def _analyze_av_sync(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Analyze audio/video synchronization"""
    errors = []

    try:
        cmd = [
            ffprobe_path, '-v', 'error',
            '-show_entries', 'stream=codec_type,start_time,duration',
            '-of', 'json', file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0:
            return errors

        data = json.loads(result.stdout)
        video_streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
        audio_streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']

        if video_streams and audio_streams:
            video_duration = float(video_streams[0].get('duration', 0))
            audio_duration = float(audio_streams[0].get('duration', 0))

            duration_diff = abs(video_duration - audio_duration)
            if duration_diff > 1.0:  # More than 1 second difference
                errors.append(VideoIntegrityError(
                    'av_sync', 'major',
                    f'A/V duration mismatch: video={video_duration:.2f}s, audio={audio_duration:.2f}s',
                    file_path
                ))
            elif duration_diff > 0.1:  # More than 100ms difference
                errors.append(VideoIntegrityError(
                    'av_sync', 'minor',
                    f'Minor A/V duration difference: {duration_diff:.2f}s', file_path
                ))

    except Exception as e:
        errors.append(VideoIntegrityError(
            'av_sync', 'minor',
            f'A/V sync analysis error: {str(e)}', file_path
        ))

    return errors


def _validate_stream_metadata(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Validate stream metadata consistency"""
    errors = []

    try:
        cmd = [
            ffprobe_path, '-v', 'error',
            '-show_entries', 'stream=index,codec_type,codec_name,duration,bit_rate,width,height,sample_rate',
            '-of', 'json', file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0:
            errors.append(VideoIntegrityError(
                'metadata_validation', 'major',
                f'Failed to read stream metadata: {result.stderr}', file_path
            ))
            return errors

        data = json.loads(result.stdout)
        streams = data.get('streams', [])

        for stream in streams:
            stream_type = stream.get('codec_type', 'unknown')
            codec_name = stream.get('codec_name', 'unknown')

            if stream_type == 'video':
                width = stream.get('width')
                height = stream.get('height')
                if not width or not height:
                    errors.append(VideoIntegrityError(
                        'metadata_validation', 'major',
                        f'Video stream missing resolution info: {width}x{height}',
                        file_path
                    ))
                elif width <= 0 or height <= 0:
                    errors.append(VideoIntegrityError(
                        'metadata_validation', 'major',
                        f'Invalid video resolution: {width}x{height}', file_path
                    ))

            elif stream_type == 'audio':
                sample_rate = stream.get('sample_rate')
                if not sample_rate or int(sample_rate) <= 0:
                    errors.append(VideoIntegrityError(
                        'metadata_validation', 'major',
                        f'Invalid audio sample rate: {sample_rate}', file_path
                    ))

            if codec_name == 'unknown':
                errors.append(VideoIntegrityError(
                    'metadata_validation', 'warning',
                    f'Unknown codec in {stream_type} stream', file_path
                ))

    except json.JSONDecodeError:
        errors.append(VideoIntegrityError(
            'metadata_validation', 'major',
            'Failed to parse stream metadata JSON', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'metadata_validation', 'major',
            f'Stream metadata validation error: {str(e)}', file_path
        ))

    return errors


def _validate_timestamps(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Validate timestamp consistency"""
    errors = []

    try:
        cmd = [
            ffprobe_path, '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'packet=pts_time,dts_time',
            '-of', 'csv=p=0', file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)
        if result.returncode != 0:
            return errors

        lines = result.stdout.strip().split('\n')[:100]
        prev_pts = None
        pts_errors = 0

        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    pts = float(parts[0]) if parts[0] != 'N/A' else None
                    dts = float(parts[1]) if parts[1] != 'N/A' else None

                    if prev_pts is not None and pts is not None and pts < prev_pts:
                        pts_errors += 1

                    prev_pts = pts

                except ValueError:
                    continue

        if pts_errors > 10:
            errors.append(VideoIntegrityError(
                'timestamp_validation', 'major',
                f'Many timestamp irregularities: {pts_errors} non-monotonic PTS values',
                file_path
            ))
        elif pts_errors > 0:
            errors.append(VideoIntegrityError(
                'timestamp_validation', 'minor',
                f'Some timestamp issues: {pts_errors} non-monotonic PTS values',
                file_path
            ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'timestamp_validation', 'warning',
            'Timestamp validation timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'timestamp_validation', 'minor',
            f'Timestamp validation error: {str(e)}', file_path
        ))

    return errors


def _validate_container_metadata(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Validate container-level metadata"""
    errors = []

    try:
        cmd = [
            ffprobe_path, '-v', 'error',
            '-show_entries', 'format=duration,size,bit_rate,nb_streams',
            '-of', 'json', file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if result.returncode != 0:
            return errors

        data = json.loads(result.stdout)
        format_info = data.get('format', {})

        duration = format_info.get('duration')
        if duration:
            try:
                dur_float = float(duration)
                if dur_float <= 0:
                    errors.append(VideoIntegrityError(
                        'container_metadata', 'major',
                        f'Invalid duration: {duration}', file_path
                    ))
                elif dur_float < 0.1:
                    errors.append(VideoIntegrityError(
                        'container_metadata', 'warning',
                        f'Very short duration: {duration}s', file_path
                    ))
            except ValueError:
                errors.append(VideoIntegrityError(
                    'container_metadata', 'minor',
                    f'Invalid duration format: {duration}', file_path
                ))

        # Validate file size consistency
        reported_size = format_info.get('size')
        if reported_size:
            try:
                reported_size_int = int(reported_size)
                actual_size = Path(file_path).stat().st_size

                size_diff = abs(actual_size - reported_size_int)
                if size_diff > 1024:  # More than 1KB difference
                    errors.append(VideoIntegrityError(
                        'container_metadata', 'minor',
                        f'File size mismatch: reported={reported_size_int}, actual={actual_size}',
                        file_path
                    ))
            except ValueError:
                pass

        nb_streams = format_info.get('nb_streams', 0)
        if nb_streams == 0:
            errors.append(VideoIntegrityError(
                'container_metadata', 'critical',
                'No streams found in container', file_path
            ))

    except json.JSONDecodeError:
        errors.append(VideoIntegrityError(
            'container_metadata', 'major',
            'Failed to parse container metadata JSON', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'container_metadata', 'minor',
            f'Container metadata validation error: {str(e)}', file_path
        ))

    return errors


def metadata_validation(file_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """Comprehensive metadata validation"""
    errors = []
    errors.extend(_validate_stream_metadata(file_path, ffprobe_path))
    errors.extend(_validate_timestamps(file_path, ffprobe_path))
    errors.extend(_validate_container_metadata(file_path, ffprobe_path))
    return errors


def advanced_ffmpeg_analysis(file_path: str, ffmpeg_path: str, ffprobe_path: str) -> List[VideoIntegrityError]:
    """GOP structure, bitstream, frame integrity, and A/V sync analysis"""
    errors = []
    errors.extend(_analyze_gop_structure(file_path, ffprobe_path))
    errors.extend(_validate_bitstream(file_path, ffmpeg_path))
    errors.extend(_check_frame_integrity(file_path, ffmpeg_path))
    errors.extend(_analyze_av_sync(file_path, ffprobe_path))
    return errors


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    """Entry point used by the 'metadata_validation' UI checkbox"""
    ffprobe_path = ffprobe_path or ffmpeg_path.replace('ffmpeg', 'ffprobe')
    errors = []
    errors.extend(metadata_validation(file_path, ffprobe_path))
    errors.extend(advanced_ffmpeg_analysis(file_path, ffmpeg_path, ffprobe_path))
    return format_check_result(errors, log_callback, progress_callback)
