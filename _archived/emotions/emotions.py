import tempfile
import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.database_service import upload_image_cv2
from app.services.emotions_service import get_emotions_from_image, get_emotions_from_video
from app.services.recognition_service import read_image_from_url
from app.utils.response import create_error_response, create_success_response
from app.utils.security import require_api_key


router = APIRouter(dependencies=[Depends(require_api_key)])


# una imagen de una persona , 

@router.post("/get-image-emotions")
async def emotions_image(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON")
    imagePerson = body.get("ImagePerson")
    print("ImagePerson:", imagePerson)
    
    if not imagePerson:
        raise HTTPException(status_code=400, detail="Required fields are missing in the body of the request")

    
    response_image_person = read_image_from_url(imagePerson)
            
    # Check if the respons image person was loaded successfully
    if response_image_person.get("success") is False:
        print("Error loading  image:", response_image_person.get("message") )
        return {"message": "Error loading image: " + response_image_person.get("message")}
    
    image_person=response_image_person.get("data")
    
    # call detect emotion
    
    response_get_emotions=get_emotions_from_image(image_person)
    
    if response_get_emotions.get("success") is False:
        return {"message": "Error processing image: " + response_get_emotions.get("message")}
    data = response_get_emotions.get("data")
    
    responseUploadImageEmotions= upload_image_cv2(data["image-detected"]) 
    if responseUploadImageEmotions.get("success") is False:
        return {"message": "Error uploading image: " + responseUploadImageEmotions.get("message")}

    data["image-detected"] = responseUploadImageEmotions.get("data")
    
    return JSONResponse(create_success_response(data = data, message=response_get_emotions.get("message"), code=200))



@router.post("/get-video-emotions")
async def emotions_video(request: Request): 
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON")
    
    url_video = body.get("url_video")
    frame_rate = body.get("frame_rate", 24)  
    print("url_video:", url_video)
    
    if not url_video or not frame_rate:
        raise HTTPException(status_code=400, detail="Required fields are missing in the body of the request")
    
  
    response_get_emotions= get_emotions_from_video(url_video, frame_rate)
    
    if response_get_emotions.get("success") is False:
        print("Error processing video:", response_get_emotions.get("message"))
        return  JSONResponse(create_error_response(code=500, message=response_get_emotions.get("message")))
    
    {"message": "Error processing video: " + response_get_emotions.get("message")}
    
    data= response_get_emotions.get("data")
    
    responseUploadVideoEmotions= upload_image_cv2(data["image-emotions"]) 

    
    if responseUploadVideoEmotions.get("success") is False:
        print("Error uploading video emotions image:", responseUploadVideoEmotions.get("message"))
        return JSONResponse(create_error_response(code=500, message=responseUploadVideoEmotions.get("message")))
    
    
    data["image-emotions"] = responseUploadVideoEmotions.get("data")
    print("Emotions detected successfully, returning response")
    return JSONResponse(create_success_response(data = data, message=response_get_emotions.get("message"), code=200))