"""
Persisted user settings (currently just the optional FFmpeg path override).
Stored as JSON under the OS-appropriate user config directory so it survives
PyInstaller-bundled installs where the project directory isn't writable.
"""
import json
import os
from typing import Optional

from .platform_utils import get_platform_name

_SETTINGS_FILENAME = 'settings.json'
_APP_DIR_NAME = 'VideoFileIntegrityCheck'


def _settings_dir() -> str:
    platform_name = get_platform_name()
    if platform_name == 'windows':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif platform_name == 'macos':
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, _APP_DIR_NAME)


def _settings_path() -> str:
    return os.path.join(_settings_dir(), _SETTINGS_FILENAME)


def load_settings() -> dict:
    """Load persisted settings, returning {} if none exist or the file is invalid."""
    try:
        with open(_settings_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict) -> None:
    """Persist the given settings dict, creating the config directory if needed."""
    settings_dir = _settings_dir()
    os.makedirs(settings_dir, exist_ok=True)
    with open(_settings_path(), 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)


def get_ffmpeg_override() -> Optional[str]:
    """Return the user-configured ffmpeg.exe path override, or None if unset."""
    return load_settings().get('ffmpeg_path_override') or None


def set_ffmpeg_override(ffmpeg_path: Optional[str]) -> None:
    """Persist (or clear, if ffmpeg_path is falsy) the ffmpeg.exe path override."""
    settings = load_settings()
    if ffmpeg_path:
        settings['ffmpeg_path_override'] = ffmpeg_path
    else:
        settings.pop('ffmpeg_path_override', None)
    save_settings(settings)
