"""
Image input endpoints: read a question image into text (Indra OCR, then a vision model; see tribos/vision).

Like the dataset upload, the route takes the raw Request so authentication and the Content-Length cap run before
any multipart parsing. The image is read in memory and never stored; only its transcription is returned.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.backend.auth import get_current_user
from app.backend.limits import UserConcurrencyLimiter, UserSemaphores
from tribos.config.settings import get_bool, get_int
from tribos.vision import read_image, vision_status
from tribos.vision.reader import ALLOWED_TYPES, ImageReadError

router = APIRouter(prefix="/api/vision", tags=["vision"])

_MULTIPART_OVERHEAD = 64 * 1024
# A user's images are read one at a time, and the slot is taken BEFORE the multipart body is parsed, so a user with
# several images in flight holds at most one parsed body in memory while the others wait unread. Requests a user may
# have queued are capped (over it: 429). Across users, one image is read at a time per process: OCR and CPU
# inference of a vision model are both CPU-bound.
_user_reading = UserSemaphores(1)
_user_queued = UserConcurrencyLimiter(10)
_reading = asyncio.Semaphore(1)
_BUSY_DETAIL = "Too many images are waiting to be read; wait for the current ones to finish."


def _error(code: int, detail: str, reason: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail, "reason": reason})


@router.get("/status")
async def status_endpoint(user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    return await asyncio.to_thread(vision_status)


@router.post("/read")
async def read_endpoint(request: Request, user_id: str = Depends(get_current_user)):
    if not get_bool("TRIBOS_VISION"):
        return _error(status.HTTP_404_NOT_FOUND, "Image input is turned off (TRIBOS_VISION=0).", "disabled")
    limit = int(get_int("TRIBOS_VISION_MAX_MB")) * 1024 * 1024
    length_header = request.headers.get("content-length")
    if length_header is None:
        return _error(status.HTTP_411_LENGTH_REQUIRED, "Content-Length is required for uploads.", "length_required")
    try:
        declared = int(length_header)
    except ValueError:
        return _error(status.HTTP_400_BAD_REQUEST, "Invalid Content-Length.", "bad_request")
    if declared > limit + _MULTIPART_OVERHEAD:
        return _error(status.HTTP_413_CONTENT_TOO_LARGE, f"Images are limited to {limit // (1024 * 1024)} MB.", "too_large")
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        return _error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the image as multipart/form-data.", "unsupported_type")
    if not _user_queued.try_acquire(user_id):
        return _error(status.HTTP_429_TOO_MANY_REQUESTS, _BUSY_DETAIL, "busy")
    try:
        async with _user_reading.get(user_id):
            return await _read_upload(request, limit)
    finally:
        _user_queued.release(user_id)


async def _read_upload(request: Request, limit: int):
    try:
        async with request.form(max_files=1, max_fields=4, max_part_size=64 * 1024) as form:
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "The 'file' field is required.", "missing_file")
            content_type = str(getattr(upload, "content_type", "") or "").lower()
            if content_type not in ALLOWED_TYPES:
                return _error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                              "Unsupported file type. Use PNG, JPEG, WebP, BMP, TIFF or PDF.", "unsupported_type")
            data = await upload.read(limit + 1)
            filename = str(getattr(upload, "filename", "") or "image")
    except AssertionError:
        return _error(status.HTTP_501_NOT_IMPLEMENTED, "Multipart uploads are not available on this server.",
                      "multipart_unavailable")
    if len(data) > limit:
        return _error(status.HTTP_413_CONTENT_TOO_LARGE, f"Images are limited to {limit // (1024 * 1024)} MB.", "too_large")
    async with _reading:
        try:
            reading = await read_image(data, content_type, filename)
        except ImageReadError as exc:
            return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc), "unreadable")
    return reading.to_dict()
