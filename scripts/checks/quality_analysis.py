"""Video/audio quality analysis: black frames, freeze frames, silence, clipping (the 'Quality Analysis' checkbox)."""
import subprocess
from typing import List

from .common import VideoIntegrityError, format_check_result


def _detect_black_frames(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Detect black frames in video"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-i', file_path,
            '-vf', 'blackdetect=d=0.5:pic_th=0.98:pix_th=0.1',
            '-f', 'null', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)

        black_detections = [
            line.strip() for line in result.stderr.split('\n')
            if 'blackdetect' in line and 'black_start' in line
        ]

        if len(black_detections) > 10:
            errors.append(VideoIntegrityError(
                'quality_black_frames', 'warning',
                f'Many black frames detected: {len(black_detections)} instances',
                file_path
            ))
        elif len(black_detections) > 0:
            errors.append(VideoIntegrityError(
                'quality_black_frames', 'minor',
                f'Black frames detected: {len(black_detections)} instances',
                file_path
            ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'quality_black_frames', 'warning',
            'Black frame detection timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'quality_black_frames', 'minor',
            f'Black frame detection error: {str(e)}', file_path
        ))

    return errors


def _detect_freeze_frames(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Detect freeze frames (identical consecutive frames)"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-i', file_path,
            '-vf', 'freezedetect=n=-60dB:d=2',
            '-f', 'null', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)

        freeze_detections = [
            line.strip() for line in result.stderr.split('\n')
            if 'freezedetect' in line and 'freeze_start' in line
        ]

        if len(freeze_detections) > 5:
            errors.append(VideoIntegrityError(
                'quality_freeze_frames', 'major',
                f'Multiple freeze frames detected: {len(freeze_detections)} instances',
                file_path
            ))
        elif len(freeze_detections) > 0:
            errors.append(VideoIntegrityError(
                'quality_freeze_frames', 'minor',
                f'Freeze frames detected: {len(freeze_detections)} instances',
                file_path
            ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'quality_freeze_frames', 'warning',
            'Freeze frame detection timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'quality_freeze_frames', 'minor',
            f'Freeze frame detection error: {str(e)}', file_path
        ))

    return errors


def _detect_audio_silence(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Detect audio silence periods"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-i', file_path,
            '-af', 'silencedetect=n=-50dB:d=2',
            '-f', 'null', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)

        silence_detections = [
            line.strip() for line in result.stderr.split('\n')
            if 'silencedetect' in line and 'silence_start' in line
        ]

        if len(silence_detections) > 10:
            errors.append(VideoIntegrityError(
                'quality_audio_silence', 'warning',
                f'Many silent periods detected: {len(silence_detections)} instances',
                file_path
            ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'quality_audio_silence', 'warning',
            'Audio silence detection timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'quality_audio_silence', 'minor',
            f'Audio silence detection error: {str(e)}', file_path
        ))

    return errors


def _detect_audio_clipping(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Detect audio clipping/distortion"""
    errors = []

    try:
        cmd = [
            ffmpeg_path, '-i', file_path,
            '-af', 'astats=metadata=1:reset=1',
            '-f', 'null', '-'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)

        peak_levels = []
        for line in result.stderr.split('\n'):
            if 'Peak level dB' in line:
                try:
                    parts = line.split(':')
                    if len(parts) > 1:
                        level = float(parts[1].strip())
                        peak_levels.append(level)
                except Exception:
                    continue

        # Check for clipping (levels very close to 0dB)
        clipping_peaks = [p for p in peak_levels if p > -1.0]
        if len(clipping_peaks) > 10:
            errors.append(VideoIntegrityError(
                'quality_audio_clipping', 'major',
                f'Audio clipping detected: {len(clipping_peaks)} instances near 0dBFS',
                file_path
            ))
        elif len(clipping_peaks) > 0:
            errors.append(VideoIntegrityError(
                'quality_audio_clipping', 'minor',
                f'Potential audio clipping: {len(clipping_peaks)} high-level instances',
                file_path
            ))

    except subprocess.TimeoutExpired:
        errors.append(VideoIntegrityError(
            'quality_audio_clipping', 'warning',
            'Audio clipping detection timed out', file_path
        ))
    except Exception as e:
        errors.append(VideoIntegrityError(
            'quality_audio_clipping', 'minor',
            f'Audio clipping detection error: {str(e)}', file_path
        ))

    return errors


def quality_analysis(file_path: str, ffmpeg_path: str) -> List[VideoIntegrityError]:
    """Perform video/audio quality analysis"""
    errors = []
    errors.extend(_detect_black_frames(file_path, ffmpeg_path))
    errors.extend(_detect_freeze_frames(file_path, ffmpeg_path))
    errors.extend(_detect_audio_silence(file_path, ffmpeg_path))
    errors.extend(_detect_audio_clipping(file_path, ffmpeg_path))
    return errors


def run(file_path: str, ffmpeg_path: str, ffprobe_path: str = None, log_callback=None, progress_callback=None):
    """Entry point used by the 'quality_analysis' UI checkbox"""
    errors = quality_analysis(file_path, ffmpeg_path)
    return format_check_result(errors, log_callback, progress_callback)
