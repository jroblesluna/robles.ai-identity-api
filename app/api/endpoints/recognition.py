from datetime import datetime
import traceback
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services import store
from app.utils.response import create_success_response
from app.utils.security import require_api_key


# require_api_key is a no-op unless the API_KEY env var is set, so this does
# not break the frontend until a key is configured.
router = APIRouter(dependencies=[Depends(require_api_key)])


def _serialize(doc: dict) -> dict:
    """Serialize a request doc for JSON output.

    - Converts datetimes to ISO strings.
    - Redacts the large base64 input images: the client already holds the
      originals, so echoing multi-MB strings back would bloat every response and
      the demo's on-screen JSON log. We expose only a short marker.
    """
    import copy

    out = copy.deepcopy(doc)
    for key in ("created_at", "updated_at"):
        val = out.get(key)
        if isinstance(val, datetime):
            out[key] = val.isoformat()

    inp = out.get("data", {}).get("input")
    if isinstance(inp, dict):
        for k in ("cardIdImageBase64", "faceImageBase64", "cardIdImageUrl", "faceImageUrl"):
            if inp.get(k):
                inp[k] = "<base64 image omitted>"
    return out


# Endpoint to get one request by ID
@router.get("/get/{request_id}")
def get_request_by_id(request_id: str):
    try:
        doc = store.get_request(request_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return JSONResponse(
            create_success_response(data=_serialize(doc), message="Document found", code=200)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-id")
async def verify_id_create_Request(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON")

    # Images now travel as base64 in the body (no external storage). Accept both
    # the new *Base64 keys and the legacy *Url keys (which may now carry base64).
    card_image = body.get("cardIdImageBase64") or body.get("cardIdImageUrl")
    face_image = body.get("faceImageBase64") or body.get("faceImageUrl")
    callback = body.get("callback")

    if not card_image or not face_image:
        raise HTTPException(
            status_code=400,
            detail="Required fields are missing in the body of the request",
        )

    try:
        doc = store.create_request(
            {
                "cardIdImageBase64": card_image,
                "faceImageBase64": face_image,
                "callback": callback,
            }
        )
        return JSONResponse(
            create_success_response(
                data=_serialize(doc), message="Create request successfully", code=200
            )
        )
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="error creating request: " + str(e))
