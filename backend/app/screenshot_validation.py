from io import BytesIO

from fastapi import HTTPException, Request
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000


async def read_image(request: Request, content_type: str) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Screenshots must be 20 MB or smaller.")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Screenshot data is required.")
    try:
        with Image.open(BytesIO(data)) as image:
            if Image.MIME.get(image.format) != content_type or image.format not in {"PNG", "JPEG"}:
                raise HTTPException(415, "Image contents must match the PNG or JPEG content type.")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "Screenshot dimensions are too large.")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Screenshot is not a valid, complete image.") from exc
    return bytes(data)
