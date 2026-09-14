import mimetypes
import os
import tempfile
import cv2
from feat import Detector
import urllib
import numpy as np
import time
from app.utils.response import create_error_response, create_success_response
from urllib.parse import urlparse, unquote




def map_emotion(emotion_detected: str) -> str:
    mapping = {
        "neutral": "neutral",
        "happiness": "happy",
        "surprise": "surprise",
        "sadness": "sad",
        "anger": "angry",
        "disgust": "disgust",
        "fear": "fear",
        "contempt": "contempt" 
    }

    return mapping.get(emotion_detected.lower(), emotion_detected)



def get_emotions_from_image(image: bytes):
    try:
        # Response data interface
        data_response ={
            "image-detected": None,
            "top-emotion": None,
            "probability": None,
            "emotions": None,
        }
        
    
        frame_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
       # Temporarily save the image to disk
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            temp_path = tmp.name
            cv2.imwrite(temp_path, cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

        # Initialize detector
        detector = Detector()

        # Detection
        result = detector.detect_image(temp_path)

        # Verification
        if result.empty:
            print("No face or emotion was detected in the image.")
            return create_error_response(code=400, message="No face or emotion was detected in the image") 
        else:
            emotions = result.emotions.iloc[0]       
            emotion = emotions.idxmax()               
            emotion_score = emotions.max() 

            image=cv2.putText(image, f"Emotion: {emotion}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            data_response["image-detected"] = image
            data_response["top-emotion"]= map_emotion(emotion)
            data_response["probability"]= f"{emotion_score*100:.2f}"
            data_response["emotions"]= emotions.to_dict()
            print(f"Detected emotions: {emotions.to_dict()}")
            
            print(f"Emoción detectada: {map_emotion(emotion)} ({emotion_score*100:.2f}%)" if emotion else "No se detectó ninguna emoción.")
            
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
                print("Temporary file deleted")
            
            return create_success_response(data=data_response, message="Emotions detected successfully", code=200)
    except Exception as e:
        print(f"Error processing image: {str(e)}")
        return create_error_response(code=500, message=f"Error processing image: -  {str(e)}")    
    
    
def is_video_by_extension(url: str) -> bool:
    parsed_url = urlparse(url)
    path = unquote(parsed_url.path).lower()
    return any(path.endswith(ext) for ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"])


def get_emotions_from_video(video_url : str, frame_rate: int = 24,face_detection_threshold= 0.7):
    try:
        start_time = time.time()

        # Response data interface
        data_response ={
            "image-emotions": None,
            "emotions": None,
            "time": None,
            "frame_rate": frame_rate,
            "iterations": None,
        }
        
        emotionsData= []
        
        # Validate if it is a video file by extension or by MIME
        file_type, _ = mimetypes.guess_type(video_url)
        if (not file_type or not file_type.startswith("video")) and not is_video_by_extension(video_url):
            return create_error_response(code=400, message="The link provided does not correspond to a valid video fileaaa.")

  
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
            tmp_video_path = tmp_video.name
            print(f"Downloading temporary video in: {tmp_video_path}")
            urllib.request.urlretrieve(video_url, tmp_video_path)
    
        cap_test = cv2.VideoCapture(tmp_video_path)
        if not cap_test.isOpened():
            cap_test.release()
            os.remove(tmp_video_path)
            return create_error_response(code=400, message="The video file could not be opened. Please verify that the link is a playable video..")
        cap_test.release()   
    
        detector = Detector()
        
        video_prediction = detector.detect_video(
        tmp_video_path,
        data_type="video",
        skip_frames=frame_rate,  # frame change
        face_detection_threshold=face_detection_threshold  # Threshold 
        )
        
        df = video_prediction
        video_path = df.iloc[0]["input"]

        cap = cv2.VideoCapture(video_path)
        detected_frames = df["frame"].unique()

        emotions = ["anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral"]
        output_images = []

        for frame_idx in detected_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue

            detections = df[df["frame"] == frame_idx]

            for _, row in detections.iterrows():
                x = int(row["FaceRectX"])
                y = int(row["FaceRectY"])
                w = int(row["FaceRectWidth"])
                h = int(row["FaceRectHeight"])

                # Dibujar rectángulo
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 255), 2)

                # Emoción dominante
                emotion_scores = row[emotions]
                top_emotion = emotion_scores.idxmax()
                top_score = float(emotion_scores.max()) * 100

                text = f"{map_emotion(top_emotion)}: {top_score:.1f}%"
                emotionsData.append({ "emotion": map_emotion(top_emotion), "probability": top_score})

                cv2.putText(frame, text, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Resize 
            height_target = 400
            scale = height_target / frame.shape[0]
            resized = cv2.resize(frame, (int(frame.shape[1] * scale), height_target))

            output_images.append(resized)

        cap.release()

        
        combined=None
        
        # We check if there is at least one image
        if output_images:
            # Concatenate horizontally
            combined = np.hstack(output_images)

            # borrar
            # output_path = "rostros_con_emociones.jpg"
            # cv2.imwrite(output_path, combined)
            # print(f"Imagen final guardada en: {output_path}")
        else:
            print("No images were generated.")
            return create_error_response(code=500, message=f"No emotions  were detected and generated: -  {str(e)}")    
        
        end_time = time.time()   
        elapsed_time = end_time - start_time
        
        data_response["image-emotions"] = combined    
        data_response["emotions"] = emotionsData
        data_response["time"] = f"{elapsed_time:.2f}"
        data_response["iterations"] = len(emotionsData)
        
            
        # Prepare response data
        if 'tmp_video_path' in locals() and os.path.exists(tmp_video_path):
            os.remove(tmp_video_path)
            print("temporary file deleted")   
        
        return create_success_response(data=data_response, message="Emotions detected successfully", code=200)
    except Exception as e:
        print(f"Error processing image: {str(e)}")
        return create_error_response(code=500, message=f"Error processing image: -  {str(e)}")    
    
    

