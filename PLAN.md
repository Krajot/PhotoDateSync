# Plan — Image metadata modifier from EXIF or Google Photos Takeout JSON

## Goal

A Python script that, for every image in a user-chosen folder, sets the file's **"date created"** and **"date modified"** filesystem timestamps from the best available source:

1. **EXIF `Date/Time Original`** in the image itself (interpreted as camera **local time**) — checked first.
2. If absent/unparseable, the matching Google Photos supplemental JSON `photoTakenTime.timestamp` (unix).

On success the image moves to `modified-correctly` and any matching JSON is **deleted**.

## Approach summary

- Single Python file: `modify-image-metadata.py`
- Uses **Pillow** (`pip install pillow`) to read EXIF; optional `pillow-heif` for HEIC/HEIF EXIF. Otherwise stdlib only.
- Targets Windows filesystem timestamps (no EXIF editing, no timezone math for the JSON route: unix timestamp is an absolute instant, converted directly to FILETIME).
- Interactive: asks the user once for the folder path at start.

## Flow

1. **Prompt:** paste folder path → strip surrounding quotes → validate exists → exit if not.
2. **Create output folders** inside it (if missing):
   - `modified-correctly`
   - `failed`
   - `failed-to-find-matches`
3. **Scan ONLY the top level** of the folder (subfolders excluded, so re-runs safely bypass the output folders).
4. **Ignore** (leave in place):
   - any file whose extension is not in `IMAGE_EXTENSIONS`
   - all `*.json` files (orphan or otherwise)
5. **Per image file:**

   **a) EXIF first (priority):**
   Read `Date/Time Original` (`0x9003`) via Pillow. If present and parseable as `YYYY:MM:DD HH:MM:SS`, convert to an absolute instant as **system-local time** and use it.

   **b) JSON fallback** (only if EXIF is missing/unreadable/unparseable):
   `matching JSON name = <full image filename>.supplemental-metadata.json`

   | Case | Action |
   | --- | --- |
   | no match | move image to `failed-to-find-matches`; done |
   | match + invalid JSON / missing `photoTakenTime` / missing or non-numeric `timestamp` | **FAILED** |
   | match + valid | read `photoTakenTime.timestamp` (int) |
   | timestamps set OK | **success** (see below) |
   | any OSError during the set | **FAILED** |

   **Success:** move the image alone to `modified-correctly` and **delete** any matching JSON (whether the date came from EXIF or JSON).

   **FAILED:** move image (+ JSON if present) to `failed` and write `<image file name>.txt` report with: image name, error message, run date (overwritten on re-run).

6. **Print summary counts** at end.

## Key decisions / answers from user

- "date created" and "date modified" = **OS filesystem timestamps**.
- **EXIF priority**: if the image has a parseable `Date/Time Original`, it wins; otherwise fall back to JSON.
- EXIF `Date/Time Original` carries no timezone → interpreted as **system-local time** (camera convention); converted to an absolute instant before writing.
- Support all common image formats; if processing fails, send to `failed` with a report.
- Matching is always by **exact filename**: `"X.jpg"` → `"X.jpg.supplemental-metadata.json"`.
- **Move** (not copy) images; on success the JSON is **deleted** (it is not kept alongside the image).
- JSON route uses `photoTakenTime.timestamp` (unix value); unix timestamp converts straight to file time.
- **Overwrite** existing destination files and reports on re-runs.
- Image detection: **fixed extension list** (`jpg, jpeg, png, gif, bmp, tif, tiff, webp, heic, heif, cr2, nef, arw` — case-insensitive).
- **Top level only.** Orphan JSONs / unrelated files ignored.
- Dependency: **Pillow** (+ optional `pillow-heif` for HEIC). Everything else stdlib (`ctypes` for Windows creation time; `os.utime` for modified).

## Implementation details

- EXIF read: `PIL.Image.open(path).getexif()` → tag `0x9003` (`DateTimeOriginal`); parse `"%Y:%m:%d %H:%M:%S"`, convert with `time.mktime` (system-local).
- Set modified time: `os.utime(path, (atime, unix_ts))`
- Set creation time (Windows): `kernel32.SetFileTime` via `ctypes`
  - `FILETIME = (unix_ts + 11644473600) * 10_000_000`
  - handle opened with `GENERIC_WRITE`
- Moves: helper removes an existing destination first, then `shutil.move` (Windows `os.rename` fails if destination exists).
- JSON timestamp may arrive as `str` (`"1554563902"`) or `int` → `int()` it.
- `IMAGE_EXTENSIONS` constant is easily editable at top of file.
- Pillow/HEIC: `pillow_heif` opener is registered if available; otherwise HEIC falls back to the JSON route.

## Verification

- Build a test folder in temp with:
  - image **with** EXIF `Date/Time Original` + a JSON with a different timestamp → `modified-correctly`, date from EXIF, JSON deleted
  - image **without** EXIF + valid JSON → `modified-correctly`, JSON deleted
  - image with NO EXIF and NO JSON → `failed-to-find-matches`
  - image with NO EXIF + JSON missing `photoTakenTime` → `failed` + report
  - a non-image file and an orphan JSON → ignored
- Run script, confirm folder placement + written dates match the expected source (compare via `Get-Item .CreationTime` / `.LastWriteTime`).

## Notes

- Original real-data run (JSON-only logic): 91 modified-correctly, 0 failed, 10 failed-to-find-matches (the `*-edited.jpeg` versions have no JSON).
- Behavior change: JSON metadata is now **deleted** on success instead of being kept with the image; EXIF `Date/Time Original` now takes priority over JSON.