# Plan — Image metadata modifier from Google Photos Takeout JSON

## Goal

A Python script that, for every image in a user-chosen folder, reads the matching Google Photos supplemental JSON metadata, and uses the `photoTakenTime.timestamp` (unix) value to set the file's **"date created"** and **"date modified"** filesystem timestamps.

## Approach summary

- Single, stdlib-only Python file: `modify-image-metadata.py`
- Targets Windows filesystem timestamps (no EXIF editing, no timezone math: unix timestamp is an absolute instant, converted directly to FILETIME).
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
   `matching JSON name = <full image filename>.supplemental-metadata.json`

   | Case | Action |
   | --- | --- |
   | no match | move image to `failed-to-find-matches`; done |
   | match + invalid JSON / missing `photoTakenTime` / missing or non-numeric `timestamp` | **FAILED** |
   | match + valid | read `photoTakenTime.timestamp` (int) → set file dates (`SetFileTime` for creation, `os.utime` for modified) |
   | timestamps set OK | move image + its JSON to `modified-correctly` |
   | any OSError during the set | **FAILED** |

   **FAILED** → move image (+ JSON if found) to `failed` and write `<image file name>.txt` report with: image name, error message, run date (overwritten on re-run).

6. **Print summary counts** at end.

## Key decisions / answers from user

- "date created" and "date modified" = **OS filesystem timestamps**.
- Support all common image formats; if processing fails, send to `failed` with a report.
- Matching is always by **exact filename**: `"X.jpg"` → `"X.jpg.supplemental-metadata.json"`.
- **Move** (not copy); JSON travels with its image in every move.
- Use `photoTakenTime.timestamp` (unix value); unix timestamp converts straight to file time.
- **Overwrite** existing destination files and reports on re-runs.
- Image detection: **fixed extension list** (`jpg, jpeg, png, gif, bmp, tif, tiff, webp, heic, heif, cr2, nef, arw` — case-insensitive).
- **Top level only.** Orphan JSONs / unrelated files ignored.
- **Stdlib only** (`ctypes` for Windows creation time; `os.utime` for modified).

## Implementation details

- Set modified time: `os.utime(path, (atime, unix_ts))`
- Set creation time (Windows): `kernel32.SetFileTime` via `ctypes`
  - `FILETIME = (unix_ts + 11644473600) * 10_000_000`
  - handle opened with `GENERIC_WRITE`
- Moves: helper removes an existing destination first, then `shutil.move` (Windows `os.rename` fails if destination exists).
- JSON timestamp may arrive as `str` (`"1554563902"`) or `int` → `int()` it.
- `IMAGE_EXTENSIONS` constant is easily editable at top of file.

## Verification

- Build a test folder in temp with:
  - normal case (image + matching JSON) → `modified-correctly`
  - image with NO JSON → `failed-to-find-matches`
  - image + JSON with missing `photoTakenTime` → `failed` + report
- Run script, confirm folder placement + written dates match JSON timestamp (compare via `Get-Item .CreationTime` / `.LastWriteTime`).

## Notes

- Real data present under `Data\Takeout\Google Photos\...` was NOT used for the live test run; testing used the temp folder to avoid mutating originals.
- Test run against real folder: 91 modified-correctly, 0 failed, 10 failed-to-find-matches (the `*-edited.jpeg` versions have no JSON).