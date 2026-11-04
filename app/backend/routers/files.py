"""Download a file an answer produced (tribos.files): GET /api/files/{file_id}, only for the user who asked.
`?inline=1` serves it for viewing in the browser instead of as a download."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.backend.auth import get_current_user
from tribos.files.store import get_file_store

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{file_id}")
async def download_file(file_id: str, inline: bool = Query(default=False),
                        user_id: str = Depends(get_current_user)) -> FileResponse:
    found = get_file_store().load(user_id, file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="File not found")
    path, meta = found
    disposition = "inline" if inline else "attachment"
    return FileResponse(path, media_type=meta.get("media_type") or "application/octet-stream", headers={
        "Content-Disposition": f"{disposition}; filename=\"{meta['name']}\"; filename*=UTF-8''{quote(meta['name'])}",
        "X-Content-Type-Options": "nosniff",
    })
