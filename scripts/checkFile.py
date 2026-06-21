import os
import subprocess
import re
import struct
import json
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
import mimetypes

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

class ComprehensiveVideoChecker:
    """Comprehensive video file integrity checker with multiple validation methods"""
    
    def __init__(self, ffmpeg_path: str, ffprobe_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path or ffmpeg_path.replace('ffmpeg', 'ffprobe')
        self.errors: List[VideoIntegrityError] = []
        self.current_file_info = {}  # Store current file context
        
    def _parse_detailed_error(self, log_line: str, file_path: str) -> Optional[VideoIntegrityError]:
        """Parse FFmpeg log lines for detailed error information"""
        line = log_line.strip()
        line_lower = line.lower()
        
        # Extract timestamp if present
        timestamp = None
        frame_number = None
        additional_info = {}
        
        # Common timestamp patterns in FFmpeg output
        import re
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
                # Try to extract frame number from the match
                if match.groups():
                    try:
                        extracted_frame = int(match.group(1))
                        if frame_number is None:
                            frame_number = extracted_frame
                    except (ValueError, IndexError):
                        pass
                
                # Create detailed message
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
        
    def validate_file_header(self, file_path: str) -> List[VideoIntegrityError]:
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
        
    def validate_file_structure(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate container-specific file structure"""
        errors = []
        
        try:
            file_ext = Path(file_path).suffix.lower()
            
            if file_ext in ['.mp4', '.m4v', '.mov']:
                errors.extend(self._validate_mp4_structure(file_path))
            elif file_ext in ['.avi']:
                errors.extend(self._validate_avi_structure(file_path))
            elif file_ext in ['.mkv', '.webm']:
                errors.extend(self._validate_matroska_structure(file_path))
                
        except Exception as e:
            errors.append(VideoIntegrityError(
                'file_structure', 'major',
                f'Structure validation failed: {str(e)}', file_path
            ))
            
        return errors
        
    def _validate_mp4_structure(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate MP4/MOV container structure"""
        errors = []
        
        try:
            with open(file_path, 'rb') as f:
                # Check for moov atom
                found_moov = False
                found_mdat = False
                
                while True:
                    atom_header = f.read(8)
                    if len(atom_header) < 8:
                        break
                        
                    atom_size, atom_type = struct.unpack('>I4s', atom_header)
                    
                    if atom_type == b'moov':
                        found_moov = True
                    elif atom_type == b'mdat':
                        found_mdat = True
                        
                    # Skip to next atom
                    if atom_size > 8:
                        f.seek(atom_size - 8, 1)
                    else:
                        break
                        
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
        
    def _validate_avi_structure(self, file_path: str) -> List[VideoIntegrityError]:
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
        
    def _validate_matroska_structure(self, file_path: str) -> List[VideoIntegrityError]:
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
        
    def check_file_corruption(self, file_path: str) -> List[VideoIntegrityError]:
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
        
    def advanced_ffmpeg_analysis(self, file_path: str) -> List[VideoIntegrityError]:
        """Perform advanced FFmpeg-based analysis"""
        errors = []
        
        # GOP structure analysis
        errors.extend(self._analyze_gop_structure(file_path))
        
        # Bitstream validation
        errors.extend(self._validate_bitstream(file_path))
        
        # Frame integrity check
        errors.extend(self._check_frame_integrity(file_path))
        
        # Audio/video sync analysis
        errors.extend(self._analyze_av_sync(file_path))
        
        return errors
        
    def _analyze_gop_structure(self, file_path: str) -> List[VideoIntegrityError]:
        """Analyze GOP (Group of Pictures) structure"""
        errors = []
        
        try:
            cmd = [
                self.ffprobe_path, '-v', 'error',
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
                
            # Analyze frame types
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
        
    def _validate_bitstream(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate video bitstream syntax with detailed error reporting"""
        errors = []
        
        try:
            cmd = [
                self.ffmpeg_path, '-v', 'info',
                '-i', file_path,
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            
            # Parse stderr for specific error patterns with detailed analysis
            stderr_lines = result.stderr.split('\n')
            frame_errors = {}  # Track errors per frame
            
            for line in stderr_lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Try detailed error parsing first
                detailed_error = self._parse_detailed_error(line, file_path)
                if detailed_error:
                    errors.append(detailed_error)
                    
                    # Track frame-specific errors
                    if detailed_error.frame_number:
                        if detailed_error.frame_number not in frame_errors:
                            frame_errors[detailed_error.frame_number] = []
                        frame_errors[detailed_error.frame_number].append(detailed_error.error_type)
                        
            # Add summary for multiple frame errors
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
        
    def _check_frame_integrity(self, file_path: str) -> List[VideoIntegrityError]:
        """Check individual frame integrity with detailed frame information"""
        errors = []
        
        try:
            # Use framemd5 to verify frame checksums and get detailed frame info
            cmd = [
                self.ffmpeg_path, '-v', 'info',
                '-i', file_path,
                '-f', 'framemd5', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=60)
            
            if result.returncode != 0:
                # Parse stderr for detailed frame errors
                frame_count = 0
                corrupt_frames = []
                
                for line in result.stderr.split('\n'):
                    if not line.strip():
                        continue
                        
                    # Try to parse detailed error
                    detailed_error = self._parse_detailed_error(line, file_path)
                    if detailed_error:
                        errors.append(detailed_error)
                        
                        if detailed_error.frame_number:
                            corrupt_frames.append(detailed_error.frame_number)
                            
                    # Count total frames processed
                    if 'frame=' in line:
                        frame_match = re.search(r'frame=\s*(\d+)', line)
                        if frame_match:
                            frame_count = max(frame_count, int(frame_match.group(1)))
                
                # Add general frame integrity error if no specific errors found
                if not errors:
                    errors.append(VideoIntegrityError(
                        'frame_integrity', 'major',
                        f'Frame integrity check failed after processing {frame_count} frames: {result.stderr}',
                        file_path,
                        additional_info={'frames_processed': frame_count}
                    ))
                elif corrupt_frames:
                    # Summary of corrupted frames
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
                # Count frames processed successfully
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
        
    def _analyze_av_sync(self, file_path: str) -> List[VideoIntegrityError]:
        """Analyze audio/video synchronization"""
        errors = []
        
        try:
            cmd = [
                self.ffprobe_path, '-v', 'error',
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
        
    def quality_analysis(self, file_path: str) -> List[VideoIntegrityError]:
        """Perform video/audio quality analysis"""
        errors = []
        
        # Black frame detection
        errors.extend(self._detect_black_frames(file_path))
        
        # Freeze frame detection
        errors.extend(self._detect_freeze_frames(file_path))
        
        # Audio silence detection
        errors.extend(self._detect_audio_silence(file_path))
        
        # Audio clipping detection
        errors.extend(self._detect_audio_clipping(file_path))
        
        return errors
        
    def _detect_black_frames(self, file_path: str) -> List[VideoIntegrityError]:
        """Detect black frames in video"""
        errors = []
        
        try:
            cmd = [
                self.ffmpeg_path, '-i', file_path,
                '-vf', 'blackdetect=d=0.5:pic_th=0.98:pix_th=0.1',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)
            
            # Parse black frame detections
            black_detections = []
            for line in result.stderr.split('\n'):
                if 'blackdetect' in line and 'black_start' in line:
                    black_detections.append(line.strip())
                    
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
        
    def _detect_freeze_frames(self, file_path: str) -> List[VideoIntegrityError]:
        """Detect freeze frames (identical consecutive frames)"""
        errors = []
        
        try:
            cmd = [
                self.ffmpeg_path, '-i', file_path,
                '-vf', 'freezedetect=n=-60dB:d=2',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)
            
            # Parse freeze detections
            freeze_detections = []
            for line in result.stderr.split('\n'):
                if 'freezedetect' in line and 'freeze_start' in line:
                    freeze_detections.append(line.strip())
                    
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
        
    def _detect_audio_silence(self, file_path: str) -> List[VideoIntegrityError]:
        """Detect audio silence periods"""
        errors = []
        
        try:
            cmd = [
                self.ffmpeg_path, '-i', file_path,
                '-af', 'silencedetect=n=-50dB:d=2',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)
            
            # Parse silence detections
            silence_detections = []
            for line in result.stderr.split('\n'):
                if 'silencedetect' in line and 'silence_start' in line:
                    silence_detections.append(line.strip())
                    
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
        
    def _detect_audio_clipping(self, file_path: str) -> List[VideoIntegrityError]:
        """Detect audio clipping/distortion"""
        errors = []
        
        try:
            cmd = [
                self.ffmpeg_path, '-i', file_path,
                '-af', 'astats=metadata=1:reset=1',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)
            
            # Look for peak levels near 0dBFS indicating potential clipping
            peak_levels = []
            for line in result.stderr.split('\n'):
                if 'Peak level dB' in line:
                    try:
                        # Extract peak level value
                        parts = line.split(':')
                        if len(parts) > 1:
                            level = float(parts[1].strip())
                            peak_levels.append(level)
                    except:
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
        
    def metadata_validation(self, file_path: str) -> List[VideoIntegrityError]:
        """Comprehensive metadata validation"""
        errors = []
        
        # Stream information validation
        errors.extend(self._validate_stream_metadata(file_path))
        
        # Timestamp consistency check
        errors.extend(self._validate_timestamps(file_path))
        
        # Container metadata validation
        errors.extend(self._validate_container_metadata(file_path))
        
        return errors
        
    def _validate_stream_metadata(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate stream metadata consistency"""
        errors = []
        
        try:
            cmd = [
                self.ffprobe_path, '-v', 'error',
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
            
            # Check for missing essential metadata
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
                        
                # Check for unknown codecs
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
        
    def _validate_timestamps(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate timestamp consistency"""
        errors = []
        
        try:
            cmd = [
                self.ffprobe_path, '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'packet=pts_time,dts_time',
                '-of', 'csv=p=0', file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)
            if result.returncode != 0:
                return errors
                
            # Check first 100 packets for timestamp issues
            lines = result.stdout.strip().split('\n')[:100]
            prev_pts = None
            pts_errors = 0
            
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 2:
                    try:
                        pts = float(parts[0]) if parts[0] != 'N/A' else None
                        dts = float(parts[1]) if parts[1] != 'N/A' else None
                        
                        # Check for decreasing PTS (should be monotonic)
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
        
    def _validate_container_metadata(self, file_path: str) -> List[VideoIntegrityError]:
        """Validate container-level metadata"""
        errors = []
        
        try:
            cmd = [
                self.ffprobe_path, '-v', 'error',
                '-show_entries', 'format=duration,size,bit_rate,nb_streams',
                '-of', 'json', file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            if result.returncode != 0:
                return errors
                
            data = json.loads(result.stdout)
            format_info = data.get('format', {})
            
            # Validate duration
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
                    
            # Check stream count
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
        
    def external_tool_analysis(self, file_path: str) -> List[VideoIntegrityError]:
        """Analysis using external tools (MediaInfo, etc.)"""
        errors = []
        
        # Try MediaInfo if available
        errors.extend(self._mediainfo_analysis(file_path))
        
        return errors
        
    def _mediainfo_analysis(self, file_path: str) -> List[VideoIntegrityError]:
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
                except:
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
        
    def comprehensive_check(self, file_path: str) -> Tuple[List[VideoIntegrityError], Dict[str, Any]]:
        """Perform comprehensive integrity check using all methods"""
        self.errors = []
        
        # File-level checks
        self.errors.extend(self.validate_file_header(file_path))
        self.errors.extend(self.validate_file_structure(file_path))
        self.errors.extend(self.check_file_corruption(file_path))
        
        # Advanced FFmpeg analysis
        self.errors.extend(self.advanced_ffmpeg_analysis(file_path))
        
        # Metadata validation
        self.errors.extend(self.metadata_validation(file_path))
        
        # Quality analysis
        self.errors.extend(self.quality_analysis(file_path))
        
        # External tools analysis
        self.errors.extend(self.external_tool_analysis(file_path))
        
        # Generate summary statistics
        stats = self._generate_statistics()
        
        return self.errors, stats
        
    def _generate_statistics(self) -> Dict[str, Any]:
        """Generate summary statistics of detected issues"""
        stats = {
            'total_errors': len(self.errors),
            'by_severity': {'critical': 0, 'major': 0, 'minor': 0, 'warning': 0},
            'by_category': {}
        }
        
        for error in self.errors:
            # Count by severity
            stats['by_severity'][error.severity] += 1
            
            # Count by category
            category = error.error_type
            if category not in stats['by_category']:
                stats['by_category'][category] = 0
            stats['by_category'][category] += 1
            
        return stats

def check_video_file(file, ffmpeg_path, check_method='basic', log_callback=None, progress_callback=None):
    """
    Enhanced video file checker with comprehensive integrity analysis.
    
    Returns tuple: (returncode, log_content, detailed_errors, statistics)
    check_method options:
    - 'basic': Original basic check
    - 'frame_crc': Frame CRC validation  
    - 'frame_md5': Frame MD5 validation
    - 'stream_analysis': Stream analysis
    - 'sync_check': A/V sync check
    - 'comprehensive': All available checks (NEW)
    - 'file_validation': File header/structure validation (NEW)
    - 'quality_analysis': Video/audio quality analysis (NEW)
    - 'metadata_validation': Metadata consistency checks (NEW)
    """
    
    # Use comprehensive checker for new methods
    if check_method in ['comprehensive', 'file_validation', 'quality_analysis', 'metadata_validation']:
        ffprobe_path = ffmpeg_path.replace('ffmpeg', 'ffprobe')
        checker = ComprehensiveVideoChecker(ffmpeg_path, ffprobe_path)
        
        errors = []
        stats = {}
        
        if check_method == 'comprehensive':
            errors, stats = checker.comprehensive_check(file)
        elif check_method == 'file_validation':
            errors.extend(checker.validate_file_header(file))
            errors.extend(checker.validate_file_structure(file))
            errors.extend(checker.check_file_corruption(file))
            checker.errors = errors  # Set errors for stats generation
            stats = checker._generate_statistics()
        elif check_method == 'quality_analysis':
            errors = checker.quality_analysis(file)
            checker.errors = errors  # Set errors for stats generation
            stats = checker._generate_statistics()
        elif check_method == 'metadata_validation':
            errors = checker.metadata_validation(file)
            checker.errors = errors  # Set errors for stats generation
            stats = checker._generate_statistics()
            
        # Format output for log callback
        log_lines = []
        for error in errors:
            severity_tag = f"[{error.severity.upper()}]"
            detailed_msg = error.get_detailed_message()
            log_line = f"{severity_tag} {error.error_type}: {detailed_msg}"
            log_lines.append(log_line)
            if log_callback:
                log_callback(log_line)
                
        # Summary statistics
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
            
        # Return code based on severity
        returncode = 0
        if stats['by_severity']['critical'] > 0:
            returncode = 2
        elif stats['by_severity']['major'] > 0:
            returncode = 1
            
        if progress_callback:
            progress_callback(100)
            
        return returncode, '\n'.join(log_lines), errors, stats
    
    # Original implementation for legacy methods
    # Get total duration first
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

    # Build command based on check method
    cmd = [ffmpeg_path]
    
    if check_method == 'frame_crc':
        cmd.extend(['-v', 'info', '-i', file, '-f', 'framemd5', '-hash', 'crc', '-'])
    elif check_method == 'frame_md5':
        cmd.extend(['-v', 'info', '-i', file, '-f', 'framemd5', '-hash', 'md5', '-'])
    elif check_method == 'stream_analysis':
        cmd.extend(['-v', 'info', '-analyzeduration', '2147483647', '-probesize', '2147483647', '-i', file, '-f', 'null', '-'])
    elif check_method == 'sync_check':
        cmd.extend(['-v', 'info', '-i', file, '-vf', r'select=eq(pict_type\,I)', '-vsync', '0', '-f', 'null', '-'])
    else:  # basic check (default)
        cmd.extend(['-v', 'info', '-ignore_chapters', '1', '-i', file, '-f', 'null', '-'])
        
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
        return process.returncode, log_content, [], {}  # Empty errors/stats for legacy methods
    except Exception as e:
        if log_callback:
            log_callback(str(e))
        if progress_callback:
            progress_callback(100)
        return -1, str(e), [], {}


def get_available_check_methods():
    """Get list of all available check methods with descriptions"""
    return {
        'basic': 'Basic integrity check using FFmpeg null output',
        'frame_crc': 'Frame-level CRC validation',
        'frame_md5': 'Frame-level MD5 validation', 
        'stream_analysis': 'Extended stream analysis with deep probing',
        'sync_check': 'Audio/video synchronization check',
        'comprehensive': 'Complete analysis using all available methods',
        'file_validation': 'File header, structure, and corruption validation',
        'quality_analysis': 'Video/audio quality analysis (black frames, silence, etc.)',
        'metadata_validation': 'Metadata consistency and timestamp validation'
    }