import httpx
from app.database.config import conect_to_firestoreDataBase
from app.services.database_service import upload_image_cv2
from app.services.recognition_service import compare_verify_faces, read_image_from_url
from app.utils.others import convert_numpy_types
from datetime import datetime, timezone
from google.cloud.firestore_v1.base_query import FieldFilter # type: ignore


db = conect_to_firestoreDataBase()

async def  run_cron_verify_id():
    try:
        query = db.collection("request").where(filter=FieldFilter("status", "==", "pending"))
        results_list = list(query.stream())
        
        # Check if there are any pending requests
        if len(results_list) == 0:
            print("No pending requests found.")
            return {"message": "No pending requests found."}

        for pending_request in results_list:
            doc_ref = db.collection("request").document(pending_request.id)
            print(f"Starting execution for the request: {pending_request.id}")
            # update the status to "started"
            doc_ref.update({"status": "started"})
            # Convert the document to a dictionary
            data = pending_request.to_dict()
            #  Get input data from the document
            faceImageUrl = data.get("data").get("input").get("faceImageUrl")
            cardIdImageUrl = data.get("data").get("input").get("cardIdImageUrl")
            callback= data.get("data").get("input").get("callback")
            # output structure model
            data_response_compareFace_final ={
                "CardImageCV2": "pending",
                "FaceImageCV2": "pending",
                "CardLandMarksImage": "pending",
                "FaceLandMarksImage": "pending",
                "distance":None,
                "result_match": None,
            }
            # Update the document with the initial output structure
            doc_ref.update({"data.output": data_response_compareFace_final , "updated_at": datetime.now(timezone.utc)})

            response_card_image_cv2 = read_image_from_url(cardIdImageUrl)
            
            # Check if the image card was loaded successfully
            if response_card_image_cv2.get("success") is False:
                print("Error loading card image:", response_card_image_cv2.get("message") )
                doc_ref.update({"message":"Error loading card image - "+ response_card_image_cv2.get("message") , "updated_at": datetime.now(timezone.utc) , "success": False,"status": "failed"})
                #poner failed a todo
                continue
                
            # Read the face image from the URL                
            response_face_image_cv2 = read_image_from_url(faceImageUrl)
        
            # Check if the image Face was loaded successfully
            if response_face_image_cv2.get("success") is False:
                print("Error loading face image:", response_face_image_cv2.get("message"))
                doc_ref.update({"message":"Error loading face image - "+ response_face_image_cv2.get("message") , "updated_at": datetime.now(timezone.utc), "success": False,"status": "failed"})
                  #poner failed a todo
                continue
            
            image_card=response_card_image_cv2.get("data")
            face_card=response_face_image_cv2.get("data")
            
            # compare the images
            response_matched=compare_verify_faces(image_card, face_card)   
            
            found_errors=False 
            text_errors=[]
            
           #  Check if the images were compared successfully
            if response_matched.get("success") is False:
                print("Error comparing images:", response_matched.get("message"))
                doc_ref.update({"message":"Error comparing images - "+ response_matched.get("message") , "updated_at": datetime.now(timezone.utc), "success": False,"status": "failed"})
                found_errors=True
                text_errors.append(response_matched.get("message")) 
                
            # Upload the images to the firebase database
        
            data_compare=response_matched.get("data")
            
            if response_matched.get("success") is True:
                doc_ref.update({"data.output.distance": data_compare.get("distance")  ,  "data.output.result_match": bool(data_compare.get("match")) ,  "updated_at": datetime.now(timezone.utc), "message": "Identity successfully compared","status": "partially_completed"})
            
            
            if data_compare is None:
                print("Error comparing images: No data returned from the comparison.")
                async with httpx.AsyncClient() as client:
                    try:
                        # Make the POST request to the callback URL with the result 
                        response = await client.post(callback, json={
                            "request_id": pending_request.id,
                            "success": False,
                            "message": response_matched.get("message"),
                            "result_match": None,
                            "distance": None,
                            
                        })
                        response.raise_for_status()
                    except Exception as e:
                        found_errors=True 
                        print(f"Error calling callback url - {callback} : {e}")
                        text_errors.append(f"Error calling callback url - {callback} : {e}")
                   
                    
            
            else:    
            # Call the callback function 
                async with httpx.AsyncClient() as client:
                    try:
                        # Make the POST request to the callback URL with the result 
                        response = await client.post(callback, json={
                            "request_id": pending_request.id,
                            "success": response_matched.get("success"),
                            "message": response_matched.get("message"),
                            "result_match": bool(data_compare.get("match")) if data_compare.get("match") is not None else None,
                            "distance": data_compare.get("distance"),
                            
                        })
                        response.raise_for_status()
                    except Exception as e:
                        found_errors=True 
                        print(f"Error calling callback url - {callback} : {e}")
                        text_errors.append(f"Error calling callback url - {callback} : {e}")
           
            
                   
           
            # Upload the images to the firebase database
            responseUploadCardImage= upload_image_cv2(data_compare.get("CardImageCV2")) 
            
            # Check if the card image was uploaded successfully
            if responseUploadCardImage.get("success") is False:
                found_errors=True
                text_errors.append(responseUploadCardImage.get("message"))
                print("Error uploading card image:", responseUploadCardImage.get("message"))
                
            # Update the document with the uploaded card image     
            doc_ref.update({"data.output.CardImageCV2": (responseUploadCardImage.get("data") if  responseUploadCardImage.get("success") is True else None)  , "updated_at": datetime.now(timezone.utc) })

            # Upload the face image to the firebase database
            responseUploadFaceImage= upload_image_cv2(data_compare.get("FaceImageCV2")) 
            
            # Check if the face image was uploaded successfully
            if responseUploadFaceImage.get("success") is False:
                found_errors=True
                text_errors.append(responseUploadFaceImage.get("message"))
                print("Error uploading face image:", responseUploadFaceImage.get("message"))
            
            # Update the document with the uploaded face image
            doc_ref.update({"data.output.FaceImageCV2": (responseUploadFaceImage.get("data") if  responseUploadFaceImage.get("success") is True else None), "updated_at": datetime.now(timezone.utc)})
            
            if data_compare.get("CardLandMarksImage") is not None:
                
                responseUploadCardLandMark= upload_image_cv2( data_compare.get("CardLandMarksImage")) 
            
                # Check if the card landmarks image was uploaded successfully
                if responseUploadCardLandMark.get("success") is False:
                    found_errors=True
                    text_errors.append(responseUploadCardLandMark.get("message"))
                    print("Error uploading card landmarks image:", responseUploadCardLandMark.get("message"))
                    # Update the document with the uploaded card landmarks image    
                doc_ref.update({"data.output.CardLandMarksImage": (responseUploadCardLandMark.get("data") if  responseUploadCardLandMark.get("success") is True else "failed" ), "updated_at": datetime.now(timezone.utc)})    
              
            else:
                doc_ref.update({"data.output.CardLandMarksImage": "failed", "updated_at": datetime.now(timezone.utc)})          
            
            
            if data_compare.get("FaceLandMarksImage") is not None:
                
                # Upload the face landmarks image to the firebase database    
                responseUploadFaceLandMarks= upload_image_cv2(data_compare.get("FaceLandMarksImage")) 
                
                # Check if the face landmarks image was uploaded successfully
                if responseUploadFaceLandMarks.get("success") is False:
                    found_errors=True
                    text_errors.append(responseUploadFaceLandMarks.get("message"))
                    print("Error uploading face landmarks image:", responseUploadFaceLandMarks.get("message"))
            
                # Update the document with the uploaded face landmarks image
                doc_ref.update({"data.output.FaceLandMarksImage":( responseUploadFaceLandMarks.get("data") if  responseUploadFaceLandMarks.get("success")  is True else "failed") , "updated_at": datetime.now(timezone.utc)})
            else:
                doc_ref.update({"data.output.FaceLandMarksImage": "failed", "updated_at": datetime.now(timezone.utc)})
            
            # If any error occurred during the upload
            if found_errors:
                doc_ref.update({"status": "completed_with_errors", "success": True, "updated_at": datetime.now(timezone.utc), "message": "Request processed successfully but with errors. - Error(s): " + ", ".join(text_errors)})
                
            else:    
            # Update the document status to "completed" and set success to True
                doc_ref.update({"status": "completed", "success": True, "updated_at": datetime.now(timezone.utc) , "message": "Request processed successfully."})
            
        return {"message": "Pending requests updated successfully."}

    except Exception as e:
        print(f"Error fetching pending requests: {e}")
        return {"error": str(e)}

