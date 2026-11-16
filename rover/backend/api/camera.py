"""Endpoints de cámara: estado y vídeo MJPEG."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/camera")

BOUNDARY = "frame"


@router.get("/status")
def camera_status(request: Request) -> dict:
    return request.app.state.camera.status()


@router.get("/stream")
async def camera_stream(request: Request):
    """multipart/x-mixed-replace: se muestra con un simple <img src="/api/camera/stream">."""
    cam = request.app.state.camera
    if cam.select() is None:
        raise HTTPException(status_code=503, detail=cam.status()["detail"])

    async def body():
        async for frame in cam.frames():
            yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n").encode()
            yield frame
            yield b"\r\n"

    return StreamingResponse(
        body(),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )
