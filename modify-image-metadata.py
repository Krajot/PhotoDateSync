"""Modify image filesystem timestamps from Google Photos Takeout metadata.

For every image in a folder, reads the matching
"<image filename>.supplemental-metadata.json", takes photoTakenTime.timestamp
(unix), and writes it as the file's "date created" and "date modified".

Windows-only setting of creation time (ctypes -> SetFileTime), stdlib only.
"""

import ctypes
import json
import os
import shutil
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

# Files whose extension is in this set are treated as images.
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".tif", ".tiff", ".webp", ".heic", ".heif",
    ".cr2", ".nef", ".arw",
}

MODIFIED_CORRECTLY = "modified-correctly"
FAILED = "failed"
NO_MATCH = "failed-to-find-matches"
JSON_SUFFIX = ".supplemental-metadata.json"

UNIX_TO_FILETIME_OFFSET = 11644473600
FILETIME_TICKS_PER_SECOND = 10_000_000


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


def set_creation_time(path, unix_ts):
    """Set a file's creation time from a unix timestamp (Windows)."""
    ft = int((unix_ts + UNIX_TO_FILETIME_OFFSET) * FILETIME_TICKS_PER_SECOND)
    ft_struct = _FILETIME(ft & 0xFFFFFFFF, ft >> 32)

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = -1

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        wintypes.LPCWSTR(str(path)),
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        ok = kernel32.SetFileTime(handle, ctypes.byref(ft_struct), None, None)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def set_modified_time(path, unix_ts):
    """Set a file's last-modified time from a unix timestamp."""
    os.utime(path, (time.time(), unix_ts))


def move_overwrite(src, dst_dir):
    """Move a file into dst_dir, replacing anything with the same name."""
    dst = dst_dir / src.name
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))
    return dst


def read_timestamp(json_path):
    """Parse metadata json and return photoTakenTime.timestamp as an int."""
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    try:
        taken = data["photoTakenTime"]
        ts = int(taken["timestamp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"no valid photoTakenTime.timestamp: {exc}") from exc
    if ts <= 0:
        raise ValueError(f"timestamp is not positive: {ts}")
    return ts


def write_failure_report(image_name, error_text):
    """Write the per-image failure report next to the failed image."""
    fname = str(Path(image_name).name) + ".txt"
    fname = "".join(c for c in fname if c not in '<>:"/\\|?*')
    report = FAILED_DIR / fname
    if report.exists():
        report.unlink()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(f"Image: {image_name}\n")
        fh.write(f"Date of run: {stamp}\n")
        fh.write(f"Error: {error_text}\n")


def process_image(image_path):
    """Handle one image. Returns a status string for the summary."""
    json_path = Path(str(image_path) + JSON_SUFFIX)

    if not json_path.exists():
        move_overwrite(image_path, NO_MATCH_DIR)
        return "failed-to-find-matches"

    try:
        ts = read_timestamp(json_path)
        # Set dates BEFORE moving so the move must be an in-place rename
        # (same volume guarantees timestamps are preserved).
        set_creation_time(image_path, ts)
        set_modified_time(image_path, ts)
    except Exception as exc:
        move_overwrite(image_path, FAILED_DIR)
        if json_path.exists():
            move_overwrite(json_path, FAILED_DIR)
        write_failure_report(image_path.name, str(exc))
        return "failed"

    move_overwrite(image_path, MODIFIED_DIR)
    move_overwrite(json_path, MODIFIED_DIR)
    return "modified-correctly"


def ask_folder():
    """Return the target folder, from CLI argument or interactive prompt."""
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = input("Paste the full path of the folder containing the "
                    "images and JSON metadata: ").strip()
    raw = raw.strip().strip('"').strip("'")
    folder = Path(raw).expanduser()
    if not folder.is_dir():
        sys.exit(f"Error: folder does not exist or is not a directory: {folder}")
    return folder


def main():
    folder = ask_folder()

    global MODIFIED_DIR, FAILED_DIR, NO_MATCH_DIR
    MODIFIED_DIR = folder / MODIFIED_CORRECTLY
    FAILED_DIR = folder / FAILED
    NO_MATCH_DIR = folder / NO_MATCH
    for d in (MODIFIED_DIR, FAILED_DIR, NO_MATCH_DIR):
        d.mkdir(exist_ok=True)

    counts = {k: 0 for k in ("modified-correctly", "failed",
                             "failed-to-find-matches")}

    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        status = process_image(entry)
        counts[status] += 1
        print(f"[{status}] {entry.name}")

    print("\nDone.")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()