# PhotoDateSync

> Restore the real capture date on your photo files — from the image's own EXIF metadata or its Google Photos Takeout JSON.

**Short description:** Windows script that fixes an image's file **"date created"** and **"date modified"** so they match when the photo was actually taken, using EXIF metadate from the image `Date/Time Original` first and the matching Google Photos `photoTakenTime` metadata taken from Google Takeout as fallback.

## Problem it solves

Google Photos Takeout exports are pulled from the cloud and the files land on disk with **today's date**, not the date the photo was taken. Edited copies (e.g. `*-edited.jpeg`) can lose their dates altogether. For a folder of hundreds of photos, fixing each file by hand is impractical.

This script reads the source of truth — the embedded EXIF `Date/Time Original`, or the `photoTakenTime.timestamp` in each image's `*.supplemental-metadata.json` — and writes it onto the file's filesystem timestamps, then sorts every image into a clean result structure.

## Features

- **EXIF-first**: uses the image's embedded `Date/Time Original` when present (interpreted as camera local time).
- **JSON fallback**: otherwise reads `photoTakenTime.timestamp` (unix) from the matching `<image filename>.supplemental-metadata.json`.
- **Sets both** the file's *date created* and *date modified*.
- **Sorts output** into `modified-correctly` / `failed` / `failed-to-find-matches` subfolders.
- **Deletes the JSON** after a successful fix (kept alongside only in the `failed` folder).
- **Failure reports**: a `<image>.txt` report in `failed/` explains what went wrong for each image.
- **End-of-run summary**: prints counts plus the name and reason of every problem file.
- **Safe to re-run**: scans only the top level, overwrites existing outputs, ignores unrelated files and orphan JSONs.

## Files it works with

- **Images**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.heic`, `.heif`, `.cr2`, `.nef`, `.arw` — case-insensitive. The list is the `IMAGE_EXTENSIONS` constant near the top of the script.
- **Metadata**: `"<image filename>.supplemental-metadata.json"` in the Google Photos Takeout format.

Anything else in the folder (`.txt`, `metadata.json`, orphan JSONs, subfolders) is left untouched.

## Requirements

- Windows (creation-time change uses `SetFileTime` via `ctypes`)
- Python 3
- `pip install pillow` — for EXIF reading
- optional: `pip install pillow-heif` — for EXIF in HEIC/HEIF images (falls back to JSON otherwise)

## Usage

Run it and paste the folder path when prompted:

```sh
python modify-image-metadata.py
Paste the full path of the folder containing the images and JSON metadata: "D:\Photos\Trip 2019"
```

Or pass the path directly:

```sh
python modify-image-metadata.py "D:\Photos\Trip 2019"
```

### Result folders

Created next to your images:

| Folder | Contents |
| --- | --- |
| `modified-correctly/` | Images whose dates were fixed (matching JSONs deleted) |
| `failed/` | Images that could not be fixed + their JSON + a `.txt` report |
| `failed-to-find-matches/` | Images with no usable EXIF and no matching JSON |

## How it works

1. For every image file in the top level of the folder:
   1. Try reading EXIF `Date/Time Original` — if present and valid, use it.
   2. Otherwise look for the matching `*.supplemental-metadata.json` and use `photoTakenTime.timestamp`.
2. Write both the *date created* (Windows `SetFileTime`) and *date modified* (`os.utime`) timestamps.
3. Move the image according to the result and, on success, delete its JSON.
4. Print a `=== Summary ===` block at the end.

## Notes

- EXIF `Date/Time Original` has no timezone, so it is interpreted as **local time** (the camera convention). The unix JSON timestamp needs no conversion.
- Make a backup before running on your original Takeout export — images are **moved** (not copied) into the result folders.
