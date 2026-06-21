"""
Platform-specific utilities for cross-platform video file integrity checking
"""
import os
import platform
import sys
import tempfile
import shutil
from typing import Tuple, Optional


def get_platform_name() -> str:
    """Get standardized platform name for FFmpeg binary selection"""
    system = platform.system().lower()
    if system == 'darwin':
        return 'macos'
    elif system == 'windows':
        return 'windows'
    elif system == 'linux':
        return 'linux'
    else:
        # Default to linux for other Unix-like systems
        return 'linux'


# Global variables to store temporary FFmpeg paths
_TEMP_FFMPEG_PATH = None
_TEMP_FFPROBE_PATH = None

def get_ffmpeg_paths() -> Tuple[str, str]:
    """
    Get platform-appropriate FFmpeg and FFprobe executable paths
    
    Returns:
        Tuple of (ffmpeg_path, ffprobe_path)
    """
    global _TEMP_FFMPEG_PATH, _TEMP_FFPROBE_PATH
    
    # Determine platform and executable names
    platform_name = get_platform_name()
    
    if platform_name == 'windows':
        ffmpeg_name = 'ffmpeg.exe'
        ffprobe_name = 'ffprobe.exe'
    else:
        ffmpeg_name = 'ffmpeg'
        ffprobe_name = 'ffprobe'
    
    # Check if we're running in a PyInstaller bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # We're in a bundled app, try to use paths from _MEIPASS
        ffmpeg_bin_dir = os.path.join(sys._MEIPASS, 'ffmpeg_bin', platform_name)
        ffmpeg_path = os.path.join(ffmpeg_bin_dir, ffmpeg_name)
        ffprobe_path = os.path.join(ffmpeg_bin_dir, ffprobe_name)
        
        # Check if the bundled files exist
        if os.path.exists(ffmpeg_path) and os.path.exists(ffprobe_path):
            return ffmpeg_path, ffprobe_path
        else:
            # Fallback: extract to temporary location
            if _TEMP_FFMPEG_PATH is None or _TEMP_FFPROBE_PATH is None:
                _TEMP_FFMPEG_PATH, _TEMP_FFPROBE_PATH = _extract_ffmpeg_binaries(platform_name, ffmpeg_name, ffprobe_name)
            return _TEMP_FFMPEG_PATH, _TEMP_FFPROBE_PATH
    else:
        # We're in development mode, use original paths
        # Get the project root directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)  # Go up from utils/ to project root
        
        # Build paths
        ffmpeg_bin_dir = os.path.join(project_root, 'ffmpeg_bin', platform_name)
        ffmpeg_path = os.path.join(ffmpeg_bin_dir, ffmpeg_name)
        ffprobe_path = os.path.join(ffmpeg_bin_dir, ffprobe_name)
        
    return ffmpeg_path, ffprobe_path


def verify_ffmpeg_installation() -> Tuple[bool, str]:
    """
    Verify that FFmpeg executables exist and are accessible
    
    Returns:
        Tuple of (success, message)
    """
    try:
        ffmpeg_path, ffprobe_path = get_ffmpeg_paths()
        
        # Check if files exist
        if not os.path.isfile(ffmpeg_path):
            return False, f"FFmpeg executable not found at: {ffmpeg_path}"
        
        if not os.path.isfile(ffprobe_path):
            return False, f"FFprobe executable not found at: {ffprobe_path}"
        
        # Check if files are executable (Unix/macOS)
        platform_name = get_platform_name()
        if platform_name in ['macos', 'linux']:
            if not os.access(ffmpeg_path, os.X_OK):
                return False, f"FFmpeg is not executable: {ffmpeg_path}"
            if not os.access(ffprobe_path, os.X_OK):
                return False, f"FFprobe is not executable: {ffprobe_path}"
        
        # Additional check for Windows to ensure files are not empty
        if platform_name == 'windows':
            if os.path.getsize(ffmpeg_path) == 0:
                return False, f"FFmpeg executable is empty: {ffmpeg_path}"
            if os.path.getsize(ffprobe_path) == 0:
                return False, f"FFprobe executable is empty: {ffprobe_path}"
        
        return True, f"FFmpeg installation verified for {platform_name}"
        
    except Exception as e:
        return False, f"Error verifying FFmpeg installation: {str(e)}"


def get_system_info() -> dict:
    """Get detailed system information for debugging"""
    return {
        'platform': platform.platform(),
        'system': platform.system(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'python_version': platform.python_version(),
        'detected_platform': get_platform_name()
    }


def _extract_ffmpeg_binaries(platform_name: str, ffmpeg_name: str, ffprobe_name: str) -> Tuple[str, str]:
    """
    Extract FFmpeg binaries to a temporary directory for bundled applications
    
    Args:
        platform_name: The platform name (windows, macos, linux)
        ffmpeg_name: The FFmpeg executable name
        ffprobe_name: The FFprobe executable name
        
    Returns:
        Tuple of (ffmpeg_path, ffprobe_path) in temporary directory
    """
    try:
        # Create a temporary directory for FFmpeg binaries
        temp_dir = tempfile.mkdtemp(prefix='ffmpeg_bin_')
        
        # Determine source paths
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # In PyInstaller bundle, files are in _MEIPASS
            source_ffmpeg_bin_dir = os.path.join(sys._MEIPASS, 'ffmpeg_bin', platform_name)
        else:
            # In development, use normal path resolution
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            source_ffmpeg_bin_dir = os.path.join(project_root, 'ffmpeg_bin', platform_name)
        
        # Source paths
        source_ffmpeg = os.path.join(source_ffmpeg_bin_dir, ffmpeg_name)
        source_ffprobe = os.path.join(source_ffmpeg_bin_dir, ffprobe_name)
        
        # Destination paths in temporary directory
        dest_ffmpeg = os.path.join(temp_dir, ffmpeg_name)
        dest_ffprobe = os.path.join(temp_dir, ffprobe_name)
        
        # Copy binaries if they exist in source
        if os.path.exists(source_ffmpeg):
            shutil.copy2(source_ffmpeg, dest_ffmpeg)
        if os.path.exists(source_ffprobe):
            shutil.copy2(source_ffprobe, dest_ffprobe)
            
        # Make executables on Unix-like systems
        if platform_name in ['macos', 'linux']:
            if os.path.exists(dest_ffmpeg):
                os.chmod(dest_ffmpeg, 0o755)
            if os.path.exists(dest_ffprobe):
                os.chmod(dest_ffprobe, 0o755)
                
        return dest_ffmpeg, dest_ffprobe
    except Exception as e:
        # Fallback to original paths if extraction fails
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        ffmpeg_bin_dir = os.path.join(project_root, 'ffmpeg_bin', platform_name)
        return os.path.join(ffmpeg_bin_dir, ffmpeg_name), os.path.join(ffmpeg_bin_dir, ffprobe_name)

def make_executable(file_path: str) -> bool:
    """
    Make a file executable on Unix-like systems
    
    Args:
        file_path: Path to the file to make executable
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if get_platform_name() in ['macos', 'linux']:
            os.chmod(file_path, 0o755)
        return True
    except Exception:
        return False

def is_valid_file_path(file_path: str) -> bool:
    """
    Check if a file path contains unusual characters that might cause issues
    
    Args:
        file_path: Path to validate
        
    Returns:
        bool: True if path is valid, False otherwise
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False
            
        # Check for control characters (except common ones like newlines)
        for char in file_path:
            if ord(char) < 32 and char not in ['\n', '\r', '\t']:
                return False
                
        # Check for some problematic Unicode characters
        problematic_chars = ['\x00', '\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07',
                           '\x08', '\x0b', '\x0c', '\x0e', '\x0f', '\x10', '\x11', '\x12',
                           '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1a',
                           '\x1b', '\x1c', '\x1d', '\x1e', '\x1f']
                           
        for char in problematic_chars:
            if char in file_path:
                return False
                
        # Check for some unusual Unicode ranges that might cause issues
        for char in file_path:
            code_point = ord(char)
            # Control characters, private use areas, and some special Unicode ranges
            if (code_point >= 0xD800 and code_point <= 0xDFFF) or \
               (code_point >= 0xE000 and code_point <= 0xF8FF) or \
               (code_point >= 0xF0000 and code_point <= 0xFFFFD) or \
               (code_point >= 0x100000 and code_point <= 0x10FFFD):
                return False
                
        return True
    except Exception:
        return False

def get_invalid_path_reason(file_path: str) -> str:
    """
    Get a human-readable reason why a file path is invalid
    
    Args:
        file_path: Path to check
        
    Returns:
        str: Reason why the path is invalid, or empty string if valid
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return "File does not exist"
            
        # Check for control characters
        for i, char in enumerate(file_path):
            if ord(char) < 32 and char not in ['\n', '\r', '\t']:
                return f"Contains control character (ASCII {ord(char)}) at position {i}"
                
        # Check for specific problematic characters
        problematic_chars = ['\x00', '\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07',
                           '\x08', '\x0b', '\x0c', '\x0e', '\x0f', '\x10', '\x11', '\x12',
                           '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1a',
                           '\x1b', '\x1c', '\x1d', '\x1e', '\x1f']
                           
        for char in problematic_chars:
            if char in file_path:
                pos = file_path.find(char)
                return f"Contains problematic character (ASCII {ord(char)}) at position {pos}"
                
        # Check for unusual Unicode ranges
        for i, char in enumerate(file_path):
            code_point = ord(char)
            if (code_point >= 0xD800 and code_point <= 0xDFFF):
                return f"Contains surrogate pair character at position {i}"
            elif (code_point >= 0xE000 and code_point <= 0xF8FF):
                return f"Contains private use character at position {i}"
            elif (code_point >= 0xF0000 and code_point <= 0xFFFFD):
                return f"Contains supplementary private use character at position {i}"
            elif (code_point >= 0x100000 and code_point <= 0x10FFFD):
                return f"Contains supplementary private use character at position {i}"
                
        return ""
    except Exception as e:
        return f"Error validating path: {str(e)}"
        return False