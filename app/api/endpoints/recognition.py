from datetime import datetime, timezone
import traceback
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from app.database.config import conect_to_firestoreDataBase
from fastapi.responses import JSONResponse
from app.utils.response import create_success_response
from app.utils.security import require_api_key


# require_api_key is a no-op unless the API_KEY env var is set, so this does
# not break the frontend until a key is configured.
router = APIRouter(dependencies=[Depends(require_api_key)])
db = conect_to_firestoreDataBase()


# Endpoint to get one request by ID
@router.get("/get/{request_id}")
def get_request_by_id(request_id: str):
    try:
        doc_ref = db.collection("request").document(request_id)
        doc_snapshot = doc_ref.get()

        if not doc_snapshot.exists:
            raise HTTPException(status_code=404, detail="Document not found")

        doc_data = doc_snapshot.to_dict()

        for key in ["created_at", "updated_at"]:
            if key in doc_data and isinstance(doc_data[key], datetime):
                doc_data[key] = doc_data[key].isoformat()
                
        return JSONResponse(create_success_response(data=doc_data , message="Document found", code=200))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify-id")
async def verify_id_create_Request(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON")
    
    cardIdImageUrl = body.get("cardIdImageUrl")
    faceImageUrl = body.get("faceImageUrl")
    callback =  body.get("callback")
    
    if not cardIdImageUrl or not faceImageUrl or not callback:
         raise HTTPException(status_code=400, detail="Required fields are missing in the body of the request")

    try:
        request_data = {
            "id": None,
            "status": "pending",
            "type": None,
            "message": None,
            "success": None,
            "created_at": None,
            "updated_at": None,
            "data": {
                "input": {
                    "cardIdImageUrl": None,
                    "callback": None,
                    "faceImageUrl": None
                },
                "output": None
            }
        }

        #build the request data
        request_data["data"]["input"]["faceImageUrl"] = faceImageUrl
        request_data["data"]["input"]["cardIdImageUrl"] = cardIdImageUrl
        request_data["data"]["input"]["callback"] = callback
        request_data["type"] = "verify-id"
        request_data["created_at"] = datetime.now(timezone.utc)
        request_data["updated_at"] = datetime.now(timezone.utc)
        
        # Create request
        doc_ref = db.collection("request").add(request_data)

        if not doc_ref:
            raise HTTPException(status_code=500, detail="No se pudo crear el documento")

        # Get document ID
        doc_id = doc_ref[1].id

        load_dotenv()

        # Update the same document with its own ID
        db.collection("request").document(doc_id).update({"id": doc_id , "message": "Request created successfully"})
        
        # Read updated document
        doc_snapshot = db.collection("request").document(doc_id).get()
        if not doc_snapshot.exists:
            raise HTTPException(status_code=404, detail="request not found")

        doc_data = doc_snapshot.to_dict()
        
        # Convert datetime to ISO string for JSON
        for key in ["created_at", "updated_at"]:
            if key in doc_data and doc_data[key]:
                doc_data[key] = doc_data[key].isoformat()


        return JSONResponse(create_success_response(data=doc_data , message="Create request successfully", code=200))

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="error creating request: " + str(e))






