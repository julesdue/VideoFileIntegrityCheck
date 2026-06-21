# Video File Integrity Checker with ffmpeg

A cross-platform GUI python tool for deep video file validation on **Windows**, **macOS**, and **Linux**. Detects corruption, encoding errors, quality issues, and more using multiple advanced methods.

## Main Checks
Each method lives in its own module under `scripts/checks/` and corresponds 1:1 to a checkbox in the UI.

| Method                | Description                                 | Speed   |
|-----------------------|---------------------------------------------|---------|
| `basic`               | Quick FFmpeg null output check              | Fast    |
| `frame_crc`/`md5`     | Per-frame checksum validation               | Moderate|
| `stream_analysis`     | Deep stream/codec probing                   | Moderate|
| `sync_check`          | Audio/video sync validation                 | Fast    |
| `file_validation`     | Binary-level file structure check           | Very Fast|
| `quality_analysis`    | Detects black/freeze frames, audio issues   | Slow    |
| `metadata_validation` | Metadata/timestamp consistency, GOP/bitstream/frame/A-V sync analysis | Fast |



## Build it yourself

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
