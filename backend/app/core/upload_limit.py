import re

from starlette.responses import JSONResponse

from app.modules.papers.service import MAX_PDF_BYTES

MAX_UPLOAD_BODY_BYTES = MAX_PDF_BYTES + 1024 * 1024
_UPLOAD_PATH = re.compile(r"^/v1/spaces/[^/]+/papers/upload$")


class _UploadTooLarge(Exception):
    pass


class UploadBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not _UPLOAD_PATH.fullmatch(scope["path"]):
            return await self.app(scope, receive, send)

        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            if length < 0:
                return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
            if length > MAX_UPLOAD_BODY_BYTES:
                return await JSONResponse({"detail": "PDF upload exceeds the 30 MB limit"}, status_code=413)(scope, receive, send)

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_UPLOAD_BODY_BYTES:
                    raise _UploadTooLarge()
            return message

        try:
            return await self.app(scope, limited_receive, send)
        except _UploadTooLarge:
            return await JSONResponse({"detail": "PDF upload exceeds the 30 MB limit"}, status_code=413)(scope, receive, send)
