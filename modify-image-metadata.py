"""Modify image filesystem timestamps from EXIF or Google Photos metadata.

For every image in a folder:
  1. If the image has an EXIF "Date/Time Original" tag, use it (interpreted as
     camera local time) to write the file's "date created" and "date modified".
  2. Otherwise, look for the matching
     "<image filename>.supplemental-metadata.json", take
     photoTakenTime.timestamp (unix), and use it instead.

On success the image moves to "modified-correctly" and its JSON metadata file
(if any) is deleted. Windows-only creation-time setting via ctypes.

Dependencies (pip): pillow  (+ optional pillow-heif for HEIC/HEIF EXIF).
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

try:
    from PIL import Image, ExifTags
except ImportError:
    Image = None

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

EXIF_DATETIME_ORIGINAL = 0x9003

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


def read_exif_datetime_original(image_path):
    """Return EXIF Date/Time Original as a unix local-time timestamp.

    Returns None if Pillow is missing, the tag is absent, or it cannot be
    parsed as "YYYY:MM:DD HH:MM:SS".
    """
    if Image is None:
        return None
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            raw = exif.get(EXIF_DATETIME_ORIGINAL)
            if raw is None:
                raw = exif.get_ifd(ExifTags.IFD.Exif).get(EXIF_DATETIME_ORIGINAL)
    except Exception:
        return None
    if not raw:
        return None
    try:
        dt = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return int(time.mktime(dt.timetuple()))


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


def fail_image(image_path, json_path, error_text):
    """Move the image (+ its JSON if present) to failed + write a report."""
    move_overwrite(image_path, FAILED_DIR)
    if json_path.exists():
        move_overwrite(json_path, FAILED_DIR)
    write_failure_report(image_path.name, error_text)


def process_image(image_path):
    """Handle one image. Returns (status, detail)."""
    json_path = Path(str(image_path) + JSON_SUFFIX)

    ts = read_exif_datetime_original(image_path)

    if ts is None:
        if not json_path.exists():
            move_overwrite(image_path, NO_MATCH_DIR)
            return "failed-to-find-matches", None
        try:
            ts = read_timestamp(json_path)
        except Exception as exc:
            fail_image(image_path, json_path, str(exc))
            return "failed", str(exc)

    try:
        # Set dates BEFORE moving so the move must be an in-place rename
        # (same volume guarantees timestamps are preserved).
        set_creation_time(image_path, ts)
        set_modified_time(image_path, ts)
    except Exception as exc:
        fail_image(image_path, json_path, str(exc))
        return "failed", str(exc)

    move_overwrite(image_path, MODIFIED_DIR)
    if json_path.exists():
        json_path.unlink()
    return "modified-correctly", None


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

    results = {k: [] for k in ("modified-correctly", "failed",
                               "failed-to-find-matches")}

    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        status, detail = process_image(entry)
        results[status].append((entry.name, detail))
        print(f"[{status}] {entry.name}")

    print("\n=== Summary ===")
    for status, items in results.items():
        if status == "modified-correctly":
            print(f"modified-correctly: {len(items)}")
        elif status == "failed":
            print(f"failed: {len(items)}")
            for name, detail in items:
                print(f"  - {name}: {detail}")
        else:
            print(f"failed-to-find-matches: {len(items)}")
            for name, _ in items:
                print(f"  - {name}")


if __name__ == "__main__":
    main()