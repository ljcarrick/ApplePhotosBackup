# PhotoSync

Export Apple Photos to a NAS or backup drive — fast, resumable, family-friendly.

## What it does

- Reads your Photos library directly (no slow UI export)
- Filters by date range if needed
- Optionally converts HEIC → JPEG for better compatibility
- Resumes where it left off if interrupted
- Streams live progress in a clean browser UI

## Requirements

- macOS (Sonoma/Ventura/Monterey tested)
- Python 3.10+
- osxphotos (can install from the UI)

## Quick start

```bash
chmod +x launch.sh
./launch.sh
```

That's it. The UI opens in your browser automatically.

## Sharing with family

Share the whole `photosync/` folder (zip it, AirDrop, shared drive).
They double-click `launch.sh` — or you can wrap it in a `.app` with Platypus.

## Notes

- Export path: destination folder will be created if it doesn't exist
- Resume: re-run the same export, already-copied files are skipped
- HEIC conversion requires osxphotos (handles it internally)
- Photos edits/adjustments are NOT applied — originals only
- Faces: Synology Photos does its own face detection on import
