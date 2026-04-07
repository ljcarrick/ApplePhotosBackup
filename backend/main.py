import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="PhotoSync")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ──────────────────────────────────────────────────────────────────

def find_photos_library() -> Optional[str]:
    default = Path.home() / "Pictures" / "Photos Library.photoslibrary"
    if default.exists():
        return str(default)
    return None


def find_volumes() -> list[dict]:
    """Return mounted volumes that look like useful destinations."""
    volumes = []
    volumes_path = Path("/Volumes")
    for vol in volumes_path.iterdir():
        if vol.name.startswith("."):
            continue
        if vol.name == "Macintosh HD":
            continue
        try:
            stat = os.statvfs(vol)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
            total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
            volumes.append({
                "name": vol.name,
                "path": str(vol),
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
            })
        except Exception:
            continue
    return volumes


def check_osxphotos() -> bool:
    # Try importing directly (works when running inside venv)
    try:
        import importlib.util
        if importlib.util.find_spec("osxphotos") is not None:
            return True
    except Exception:
        pass
    # Fallback: try the CLI
    try:
        result = subprocess.run(
            [sys.executable, "-m", "osxphotos", "version"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_imagemagick() -> bool:
    try:
        result = subprocess.run(
            ["magick", "--version"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # try legacy 'convert' command
        try:
            result = subprocess.run(
                ["convert", "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

# ── routes ───────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    return {
        "photos_library": find_photos_library(),
        "volumes": find_volumes(),
        "osxphotos_installed": check_osxphotos(),
        "imagemagick_installed": check_imagemagick(),
    }


class PreflightRequest(BaseModel):
    library_path: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    convert_heic: bool = False


@app.post("/api/preflight")
def preflight(req: PreflightRequest):
    """Run osxphotos query to count photos and estimate size before export."""
    if not check_osxphotos():
        raise HTTPException(400, "osxphotos not installed")

    cmd = [
        sys.executable, "-m", "osxphotos", "query",
        "--library", req.library_path,
        "--json",
    ]
    if req.from_date:
        cmd += ["--from-date", req.from_date]
    if req.to_date:
        cmd += ["--to-date", req.to_date]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            err = result.stderr + result.stdout
            if "not readable" in err or "permission" in err.lower():
                raise HTTPException(403, "PERMISSION_DENIED")
            raise HTTPException(500, f"osxphotos error: {err}")

        photos = json.loads(result.stdout)
        total_size = 0
        for p in photos:
            if p.get("original_filesize"):
                total_size += p["original_filesize"]

        return {
            "count": len(photos),
            "size_bytes": total_size,
            "size_gb": round(total_size / (1024 ** 3), 2),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Query timed out — library may be large")
    except json.JSONDecodeError:
        raise HTTPException(500, "Failed to parse osxphotos output")


class ExportRequest(BaseModel):
    library_path: str
    destination: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    convert_heic: bool = False
    download_missing: bool = False
    sidecar_xmp: bool = False
    dry_run: bool = False


@app.post("/api/export")
async def export(req: ExportRequest):
    """Stream export progress back to client as SSE."""

    if not check_osxphotos():
        raise HTTPException(400, "osxphotos not installed")

    dest = Path(req.destination)
    if not dest.exists():
        try:
            dest.mkdir(parents=True)
        except Exception as e:
            raise HTTPException(400, f"Cannot create destination: {e}")

    cmd = [
        sys.executable, "-m", "osxphotos", "export",
        str(dest),
        "--library", req.library_path,
        "--verbose",
        "--update",          # resume: skip unchanged, copy new files
        "--filename", "{original_name}",  # use original filename
    ]

    if req.from_date:
        cmd += ["--from-date", req.from_date]
    if req.to_date:
        cmd += ["--to-date", req.to_date]

    if req.convert_heic:
        cmd += ["--convert-to-jpeg"]

    if req.download_missing:
        cmd += ["--download-missing"]

    if req.sidecar_xmp:
        cmd += ["--sidecar", "xmp"]

    if req.dry_run:
        cmd += ["--dry-run"]

    async def stream():
        yield f"data: {json.dumps({'type': 'start', 'cmd': ' '.join(cmd)})}\n\n"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        exported = 0
        skipped = 0
        errors = 0

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            # parse osxphotos verbose output for counts
            lower = line.lower()
            if "exported new file" in lower:
                exported += 1
            elif "skipping missing" in lower:
                skipped += 1
            elif "error" in lower and "exported" not in lower:
                errors += 1

            missing = 0
            if "missing:" in lower:
                import re
                m = re.search('missing:\\s*(\\d+)', line)
                if m:
                    missing = int(m.group(1))

            payload = {
                "type": "progress",
                "line": line,
                "exported": exported,
                "skipped": skipped,
                "errors": errors,
                "missing": missing,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        await proc.wait()
        returncode = proc.returncode

        yield f"data: {json.dumps({'type': 'done', 'returncode': returncode, 'exported': exported, 'skipped': skipped, 'errors': errors})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/install-osxphotos")
async def install_osxphotos():
    """Attempt to install osxphotos via pip and stream output."""
    async def stream():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "osxphotos", "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            yield f"data: {json.dumps({'line': line})}\n\n"
        await proc.wait()
        yield f"data: {json.dumps({'done': True, 'success': proc.returncode == 0})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/browse")
def browse(type: str = "folder"):
    """Open a native macOS folder/file picker via osascript and return chosen path."""
    if type == "library":
        script = """
tell application "System Events"
    activate
end tell
tell application "Finder"
    activate
end tell
set chosen to choose file of type {"com.apple.photos.library"} with prompt "Select your Photos Library" default location (path to pictures folder)
POSIX path of chosen
"""
    else:
        script = """
tell application "System Events"
    activate
end tell
set chosen to choose folder with prompt "Select export destination"
POSIX path of chosen
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        path = result.stdout.strip()
        if result.returncode != 0 or not path:
            return {"path": None}
        # Strip trailing slash for folders
        return {"path": path.rstrip("/")}
    except Exception as e:
        return {"path": None, "error": str(e)}


@app.get("/api/open-privacy-settings")
def open_privacy_settings():
    """Open macOS Privacy & Security → Photos in System Settings."""
    subprocess.Popen([
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Photos"
    ])
    return {"ok": True}


@app.get("/api/osxphotos-help")
def osxphotos_help():
    """Return osxphotos export help text for debugging."""
    result = subprocess.run(
        [sys.executable, "-m", "osxphotos", "export", "--help"],
        capture_output=True, text=True, timeout=10
    )
    return {"help": result.stdout + result.stderr}
