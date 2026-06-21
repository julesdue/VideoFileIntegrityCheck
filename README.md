# Video File Integrity Checker

A cross-platform tool for deep video file validation on **Windows**, **macOS**, and **Linux**. Detects corruption, encoding errors, quality issues, and more using multiple advanced methods. Includes a GUI and Python API.


### Windows
1. Clone/download this repo
2. Install dependencies: `pip install -r requirements.txt`
3. Download FFmpeg:
   - Visit [FFmpeg official website](https://ffmpeg.org/download.html)
   - Download the latest Windows build
   - Extract the binaries (ffmpeg.exe, ffplay.exe, ffprobe.exe) to `./ffmpeg_bin/windows/`
4. Run: `python main.py`

### macOS
1. Clone/download this repo
2. Install dependencies: `pip install -r requirements.txt`
3. Install FFmpeg: `brew install ffmpeg`
4. Copy binaries to project directory:
   ```bash
   mkdir -p ./ffmpeg_bin/macos/
   cp $(which ffmpeg) ./ffmpeg_bin/macos/
   cp $(which ffprobe) ./ffmpeg_bin/macos/
   ```
5. Make binaries executable: `chmod +x ffmpeg_bin/macos/*`
6. Run: `python main.py`

### Linux
1. Clone/download this repo
2. Install dependencies: `pip install -r requirements.txt`
3. Install FFmpeg:
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - CentOS/RHEL: `sudo yum install ffmpeg`
   - Fedora: `sudo dnf install ffmpeg`
4. Copy binaries to project directory:
   ```bash
   mkdir -p ./ffmpeg_bin/linux/
   cp $(which ffmpeg) ./ffmpeg_bin/linux/
   cp $(which ffprobe) ./ffmpeg_bin/linux/
   ```
5. Make binaries executable: `chmod +x ffmpeg_bin/linux/*`
6. Run: `python main.py`


## Main Check Methods
| Method                | Description                                 | Speed   |
|-----------------------|---------------------------------------------|---------|
| `basic`               | Quick FFmpeg null output check              | Fast    |
| `frame_crc`/`md5`     | Per-frame checksum validation               | Moderate|
| `stream_analysis`     | Deep stream/codec probing                   | Moderate|
| `sync_check`          | Audio/video sync validation                 | Fast    |
| `comprehensive`       | Runs all methods (recommended)              | Slow    |
| `file_validation`     | Binary-level file structure check           | Very Fast|
| `quality_analysis`    | Detects black/freeze frames, audio issues   | Slow    |
| `metadata_validation` | Metadata/timestamp consistency              | Fast    |



## Usage Examples

### Python API
```python
from scripts.checkFile import check_video_file, ComprehensiveVideoChecker

# Basic usage
returncode, log, errors, stats = check_video_file('video.mp4', 'ffmpeg.exe', 'comprehensive')

# Advanced usage
checker = ComprehensiveVideoChecker('ffmpeg.exe', 'ffprobe.exe')
errors, statistics = checker.comprehensive_check('video.mp4')
for error in errors:
	print(f"[{error.severity}] {error.error_type}: {error.message}")
```

### UI Application
1. Run `python main.py`
2. Drag & drop or import video files
3. Select check methods (start with 'comprehensive')
4. Click "Check Files"
5. Review results with severity indicators
6. Export logs for analysis

### Command Line Testing
```bash
python -c "from utils.platform_utils import get_platform_name; print(get_platform_name())"
python -c "from utils.platform_utils import verify_ffmpeg_installation; print(verify_ffmpeg_installation())"
python -c "from scripts.checkFile import get_available_check_methods; print(get_available_check_methods())"
```

## Contributing
1. Fork this repo
2. Create a feature branch
3. Test on your platform
4. Submit a pull request

## License
Open source. Use, modify, and distribute freely.


## Building the Application

This application can be packaged into a standalone executable using PyInstaller.

#### Manual Build
```bash
pyinstaller --name "VideoFileIntegrityChecker" --windowed --onefile --add-data "ffmpeg_bin;ffmpeg_bin" --hidden-import "PyQt6.sip" main.py
```

### Output
The executable will be created in the `dist` folder.


**For more details, see the code and comments. Most users only need this README!**