import time
from PIL import Image

# import face_recognition
import cv2
from fastapi import HTTPException
from fastapi.responses import JSONResponse
import numpy as np
import requests
import traceback
from app.services.database_service import upload_image_cv2
from app.utils.others import convert_numpy_types
from app.utils.response import create_error_response, create_success_response
from app.utils.security import IMAGE_FETCH_TIMEOUT, validate_image_url
from insightface.app import FaceAnalysis
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

PREPROCESS = False
RESIZE = True
DRAW_RECTANGLE = False
THRESHOLD_RECOGNITION = 0.6

try:
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
except Exception as e:
    raise RuntimeError(f"Error al inicializar el modelo FaceAnalysis: {e}")


# def draw_landmarks(image , face_locations=None):

#     if face_locations is None:
#       if not isinstance(image, np.ndarray):
#         image = np.array(image)
#       if image.dtype != np.uint8:
#         image = image.astype(np.uint8)
#       if not image.flags.writeable:
#         image = image.copy()

#       landmarks_list = face_recognition.face_landmarks(image)
#       if(len(landmarks_list) == 0):
#          print("No landmarks found in the image.")

#       for landmarks in landmarks_list:
#             for points in landmarks.values():
#                 for point in points:
#                     cv2.circle(image, point, 1, (0, 255, 0), -1)
#     else:
#         for face_location in face_locations:
#             landmarks_list = face_recognition.face_landmarks(image, [face_location])
#             for landmarks in landmarks_list:
#                 for points in landmarks.values():
#                     for point in points:
#                         cv2.circle(image, point, 1, (0, 255, 0), -1)
#     return image


def detect_faces(image):
    faceCascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = faceCascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=11, minSize=(100, 100)
    )
    # min size para eliminación de detección de caras pequeñas (test)
    min_area = 2000
    return [face for face in faces if face[2] * face[3] >= min_area]


def capture_face(frame, quality=False, type=""):
    global PREPROCESS, RESIZE, DRAW_RECTANGLE  # declarar uso de variables globales
    # agregar  rotación y calidad
    face_crop_found = []
    image_np = load_image_cv(frame)

    if PREPROCESS:
        image_np = preprocess_image(image_np)

    # Convertir a BGR y redimensionar si es necesario
    image_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

    image_bgr_original = image_bgr.copy()

    # if quality:
    #     cv2.imwrite('prueba_normal.jpg', image_bgr)

    if RESIZE:
        image_bgr = resize_image(image_bgr)

        # if quality:
        #     cv2.imwrite('prueba_Risize.jpg', image_bgr)

    faces = detect_faces(image_bgr)
    rotation_attempts = 0

    # Try rotating up to 3 times (90°, 180°, 270°)
    while not faces and rotation_attempts < 3 and quality == True:
        rotation_attempts += 1
        print("rotating the image 90° - hardcascade mod")
        image_bgr_original = cv2.rotate(
            image_bgr_original, cv2.ROTATE_90_COUNTERCLOCKWISE
        )
        image_bgr = image_bgr_original
        if RESIZE:
            image_bgr = resize_image(image_bgr)
        faces = detect_faces(image_bgr)

    height, width, _ = image_bgr.shape
    margin = 100

    if DRAW_RECTANGLE:
        for x, y, w, h in faces:
            cv2.rectangle(image_bgr, (x, y), (x + w, y + h), (0, 0, 255), 4)

    if faces:
        print("Face detected in the uploaded image captureFace " + type + ".")
        for x, y, w, h in faces:
            x1 = max(x - margin, 0)
            y1 = max(y - margin, 0)
            x2 = min(x + w + margin, width)
            y2 = min(y + h + margin, height)

            face_crop = image_bgr[y1:y2, x1:x2][:, :, ::-1]
            face_crop_found.append(face_crop)
    else:
        print("No face detected in the uploaded  image captureFace" + type + ".")

    return image_np, image_bgr, face_crop_found


def resize_image(image, max_size=600):
    h, w = image.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(image, (new_w, new_h))
    return image


def load_image_cv(image_file):
    if isinstance(image_file, Image.Image):
        return cv2.cvtColor(np.array(image_file), cv2.COLOR_RGB2BGR)
    elif isinstance(image_file, np.ndarray):
        return cv2.cvtColor(image_file, cv2.COLOR_BGR2RGB)
    else:
        image_file.seek(0)
        file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
        img_cv = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        return cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)


def analyze_image_quality(image_input):
    try:
        # Convert input to a NumPy RGB image
        if isinstance(image_input, Image.Image):
            img_pil = image_input
            img_np = np.array(img_pil)
        elif isinstance(image_input, np.ndarray):
            img_np = cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_np)
        else:
            image_input.seek(0)
            file_bytes = np.asarray(bytearray(image_input.read()), dtype=np.uint8)
            img_cv = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            img_np = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_np)

        width, height = img_pil.size
        img_gray = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2GRAY)
        sharpness = cv2.Laplacian(img_gray, cv2.CV_64F).var()

        # Estimate size in KB (raw size approximation)
        size_kb = img_np.nbytes / 1024

        # Apply quality rules

        if sharpness < 100:
            return False, "Blurry image - It does not meet quality requirements."
        if width < 300 or height < 300:
            return (
                False,
                "The image has a low resolution - It does not meet the quality requirements.",
            )
        if size_kb < 10:
            return (
                False,
                "very small file size requirements - It does not meet quality requirements. ",
            )

        return True, "Image meets the quality requirements."

    except Exception as e:
        return False, "An error occurred while analyzing the image."


def fast_denoise(image: np.ndarray, ksize: int = 3) -> np.ndarray:
    return cv2.GaussianBlur(image, (ksize, ksize), 0)


def sharpen_image(image: np.ndarray, strength: float = 0.2) -> np.ndarray:
    """
    Aumenta la nitidez de la imagen aplicando un filtro de convolución.

    Parámetros:
    - image: Imagen de entrada como np.ndarray.
    - strength: Multiplicador para controlar cuán fuerte es el efecto de nitidez (default 1.0).

    Retorna:
    - Imagen con mayor nitidez.
    """
    # Kernel base de sharpening
    kernel = np.array([[0, -1, 0], [-1, 5 + 4 * (strength - 1), -1], [0, -1, 0]])
    return cv2.filter2D(image, -1, kernel)


def adjust_contrast_brightness(
    image: np.ndarray, alpha: float = 1.5, beta: int = 20
) -> np.ndarray:
    """
    Ajusta el contraste y brillo de la imagen.

    Parámetros:
    - image: Imagen de entrada como np.ndarray.
    - alpha: Factor de contraste. 1.0 = sin cambio, >1 aumenta contraste.
    - beta: Valor de brillo agregado. 0 = sin cambio, >0 ilumina.

    Retorna:
    - Imagen modificada con nuevo contraste y brillo.
    """
    return cv2.convertScaleAbs(image, alpha=alpha, beta=beta)


def apply_clahe(image: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    if len(image.shape) == 3 and image.shape[2] == 3:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l2 = clahe.apply(l)
        lab = cv2.merge((l2, a, b))
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    else:
        return clahe.apply(image)


def equalize_histogram(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3 and image.shape[2] == 3:
        ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
        ycrcb[:, :, 0] = cv2.equalizeHist(ycrcb[:, :, 0])
        return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
    else:
        return cv2.equalizeHist(image)


def preprocess_image(image: np.ndarray) -> np.ndarray:
    image = fast_denoise(image)
    image = apply_clahe(image)
    # image = sharpen_image(image) #  a lot failed
    # image = adjust_contrast_brightness(image, alpha=1.5, beta=10)
    return image


def read_image_from_url(url: str):
    """
    Downloads an image from a URL and converts it to a format suitable for OpenCV.

    Parameters:
    - url: Image URL.

    Returns:
    - Image as np. ndarray.
    """
    # Validate the URL before fetching (anti-SSRF): allowed hosts only, no
    # internal/private IPs. Prevents the server from being tricked into
    # requesting cloud metadata endpoints or internal services.
    is_valid, err = validate_image_url(url)
    if not is_valid:
        return create_error_response(code=400, message=f"Invalid image URL - {err}")

    try:
        response = requests.get(url, timeout=IMAGE_FETCH_TIMEOUT)
        response.raise_for_status()  # Throws error if the response is not 200

        # Convert bytes to an OpenCV image
        image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if image is None:
            return create_error_response(
                code=400, message="The image could not be decoded."
            )
        #  return JSONResponse(status_code=400, content={"error": "The image could not be decoded.."})

        return create_success_response(
            data=image, message="Image downloaded successfully", code=200
        )

    except requests.RequestException as e:
        return create_error_response(
            code=500, message=f"Error downloading image or invalid image -  {str(e)}"
        )
    #  return JSONResponse(status_code=500, content={"error": f"Error downloading image or invalid image: {str(e)}"})


# def compare_verify_faces_old(image1: np.ndarray, image2: np.ndarray) :
#     """
#     image1 = ID card image
#     image2 = Face image
#     """
#     try:

#         data_response_compare ={
#             "CardImageCV2": None,
#             "FaceImageCV2": None,
#             "CardLandMarksImage": None,
#             "FaceLandMarksImage": None,
#             "distance": None,
#             "match": None,
#         }


#         data_response_compare["CardImageCV2"] = image1
#         data_response_compare["FaceImageCV2"] = image2


#         _, _, face_crop_found_card = capture_face(image1, True, type="- ID CARD")
#         _, _, face_crop_found_face = capture_face(image2, type="- FACE ")

#         img1_resized =  resize_image(load_image_cv(image1)) #ID CARD
#         img1_resized = preprocess_image(img1_resized)
#         img2_resized= resize_image(load_image_cv(image2)) # FACE UPLOAD
#         img2_resized = preprocess_image(img2_resized)
#         enc1=None
#         enc2=None
#         face_locations1= None
#         face_locations2= None

#         if len( face_crop_found_card) >0:
#             enc1 = face_recognition.face_encodings(load_image_cv(face_crop_found_card[0]))
#             print("Face detected in the uploaded ID image - hardcascade")
#         elif len(face_recognition.face_encodings(img1_resized)) ==0:
#             original_img1_resized=img1_resized.copy()
#             rotation_attempts = 0
#             find_enc1=  len(face_recognition.face_encodings(img1_resized)) >0
#             while not find_enc1 and rotation_attempts < 3:
#               rotation_attempts += 1
#               print("rotating the image 90° - normal mod")
#               img1_resized = cv2.rotate(img1_resized, cv2.ROTATE_90_COUNTERCLOCKWISE)
#               find_enc1=  len(face_recognition.face_encodings(img1_resized)) >0


#             if  find_enc1:
#                 print("Face detected in the uploaded ID image - normal")
#                 enc1=face_recognition.face_encodings(img1_resized)
#             else:
#                 #  tambien debo rotar?
#                 img1_resized=original_img1_resized.copy()
#                 rotation_attempts = 0
#                 face_locations1 = face_recognition.face_locations(img1_resized, model= "cnn")
#                 while not len(face_locations1) >0 and rotation_attempts < 3:
#                     rotation_attempts += 1
#                     print("rotating the image 90° - normal cnn")
#                     img1_resized = cv2.rotate(img1_resized, cv2.ROTATE_90_COUNTERCLOCKWISE)
#                     face_locations1 = face_recognition.face_locations(img1_resized, model= "cnn")

#                 if len(face_locations1) >0:
#                     print("Face detected in the uploaded ID image - CNN")
#                     enc1 = face_recognition.face_encodings(img1_resized, known_face_locations=[face_locations1[0]])
#                 else:
#                     print("No face detected in the uploaded ID image - CNN")
#                     enc1 = face_recognition.face_encodings(img1_resized)

#         else:
#             print("Face detected in the uploaded ID image")
#             # Lo encuentra a la primera
#             enc1 = face_recognition.face_encodings(img1_resized)


#         if len(face_crop_found_face) > 0:
#             print("Face detected in the uploaded face image - hardcascade")
#             enc2 = face_recognition.face_encodings(load_image_cv(face_crop_found_face[0]))
#         elif len(face_recognition.face_encodings(img2_resized)) == 0 :
#             face_locations2 = face_recognition.face_locations(img2_resized, model= "cnn")
#             if len(face_locations2) >0:
#                 print("Face detected in the uploaded face image - CNN")
#                 enc2 = face_recognition.face_encodings(img2_resized, known_face_locations=[face_locations2[0]])

#             else:
#                 print("No face detected in the uploaded face image - CNN")
#                 enc2 = face_recognition.face_encodings(img2_resized)
#         else:
#             print("Face detected in the uploaded face image")
#             enc2 = face_recognition.face_encodings(img2_resized)


#         # Put Landmarks on the images

#         if len(face_crop_found_card) > 0:
#             data_response_compare["CardLandMarksImage"] = draw_landmarks(face_crop_found_card[0].copy())[:, :, ::-1]
#         elif enc1:
#             data_response_compare["CardLandMarksImage"] =draw_landmarks(img1_resized.copy(), face_locations1)[:, :, ::-1]
#         else:
#             data_response_compare["CardLandMarksImage"] = None


#         if len(face_crop_found_face) > 0:
#             data_response_compare["FaceLandMarksImage"] = draw_landmarks(face_crop_found_face[0].copy())[:, :, ::-1]
#         elif enc2:
#             data_response_compare["FaceLandMarksImage"] =draw_landmarks(img2_resized.copy(), face_locations2)[:, :, ::-1]
#         else:
#             data_response_compare["FaceLandMarksImage"] = None


#         errors = []

#         if not enc1:
#             # ANALIZO CALIDAD
#             is_valid, quality_msg = analyze_image_quality(load_image_cv(image1))

#             errors.append(f"No face found in identity card. (1) - { quality_msg if not is_valid else "" }")

#         if not enc2:
#             # ANALIZO CALIDAD
#             is_valid, quality_msg = analyze_image_quality(load_image_cv(image2))
#             errors.append(f"No face found in captured/uploaded photo. (2) { quality_msg if not is_valid else "" }")

#         if errors:
#             return create_error_response(
#                 code=400,
#                 message="; ".join(errors),
#                 data=data_response_compare
#             )

#         else:
#              match = face_recognition.compare_faces([enc1[0]], enc2[0] ,tolerance=THRESHOLD_RECOGNITION)[0]
#              distance = face_recognition.face_distance([enc1[0]], enc2[0] )[0]

#              data_response_compare["distance"] = distance
#              data_response_compare["match"] = match


#              return create_success_response(data=data_response_compare, message="Images compared successfully", code=200)

#     except Exception as e:
#         print(traceback.format_exc())
#         return create_error_response(code=500, message=f"Error processing images: {str(e)}")


def draw_landmarks_face(imagen, landmarks):
    try:
        image_copy = imagen.copy()
        for x, y, z in landmarks:
            cv2.circle(image_copy, (int(x), int(y)), 1, (0, 255, 0), 4)

        return image_copy

    except Exception as e:
        raise RuntimeError(f"❌ Error drawing reference points: {e}")

def compare_verify_faces(image1: np.ndarray, image2: np.ndarray):
    """
    image1 = ID card image
    image2 = Face image
    """
    try:

        data_response_compare = {
            "CardImageCV2": None,
            "FaceImageCV2": None,
            "CardLandMarksImage": None,
            "FaceLandMarksImage": None,
            "distance": None,
            "match": None,
        }

        data_response_compare["CardImageCV2"] = image1
        data_response_compare["FaceImageCV2"] = image2

        # capturar las caras de las imagenes
        _, _, face_crop_found_card = capture_face(image1, True, type="- ID CARD")
        
        
        img1_resized = resize_image(load_image_cv(image1))  # ID CARD

        # Pre-process
        img1_resized = preprocess_image(img1_resized)

        img2_resized = resize_image(load_image_cv(image2))  # FACE UPLOAD
        
        # Pre-process
        img2_resized = preprocess_image(img2_resized)

        # Inicializar variables
        enc1 = None
        enc2 = None
        hardcascadeModel1 = False
        faces_enc1 = None
        faces_enc2 = None
        errors = []

        if len(face_crop_found_card) > 0:
            faces_enc1 = app.get(face_crop_found_card[0][:, :, ::-1])

            # cv2.imwrite('prueba.jpg', face_crop_found_card[0][:, :, ::-1])
            if faces_enc1:

                print("Face detected in the uploaded ID image - hardcascade")
                enc1 = faces_enc1[0].embedding

                if enc1 is None or len(enc1) == 0:
                    print(
                        "No detected landmarks in the uploaded ID image - hardcascade"
                    )
                else:
                    hardcascadeModel1 = True
                    print("Detected landmarks in the uploaded ID image - hardcascadee")

        if not faces_enc1 or enc1 is None or len(enc1) == 0:
            # rotar la imagen si no se encuentra cara tres veces
            faces_enc1 = app.get(img1_resized)

            if faces_enc1:
                print("Face detected in the uploaded ID image - normal")
                enc1 = faces_enc1[0].embedding
                if enc1 is None or len(enc1) == 0:

                    print("No detected landmarks in the uploaded ID image - normal")
                else:
                    print("Detected landmarks in the uploaded ID image - normal")

            else:

                print("No face detected in the uploaded ID image - normal")

        if not faces_enc2 or enc2 is None or len(enc2) == 0:
            # rotar la imagen si no se encuentra cara tres veces
            faces_enc2 = app.get(img2_resized)

            if faces_enc2:
                print("Face detected in the uploaded face image -  normal")
                enc2 = faces_enc2[0].embedding
                if enc2 is None or len(enc2) == 0:

                    print("No detected landmarks in the uploaded face image -  normal")
                else:
                    print("Detected landmarks in the uploaded  face image - normal")
            else:

                print("No face detected in the uploaded face image -  normal")

        # Put Landmarks on the images
        if faces_enc1 and enc1 is not None and len(enc1) > 0:
            data_response_compare["CardLandMarksImage"] = draw_landmarks_face(
                img1_resized if not hardcascadeModel1 else face_crop_found_card[0],
                faces_enc1[0].landmark_3d_68,
            )[:, :, ::-1]
        else:
            data_response_compare["CardLandMarksImage"] = None

        if faces_enc2 and enc2 is not None and len(enc2) > 0:
            data_response_compare["FaceLandMarksImage"] = draw_landmarks_face(
                img2_resized,
                faces_enc2[0].landmark_3d_68,
            )[:, :, ::-1]
        else:
            data_response_compare["FaceLandMarksImage"] = None

        if enc1 is None or len(enc1) == 0:
            # QUALITY ANALYSIS
            is_valid, quality_msg = analyze_image_quality(load_image_cv(image1))

            errors.append(
                f"No face found in identity card. (1) - { quality_msg if not is_valid else '' }"
            )

        if enc2 is None or len(enc2) == 0:
            # QUALITY ANALYSIS
            is_valid, quality_msg = analyze_image_quality(load_image_cv(image2))
            errors.append(
                f"No face found in captured/uploaded photo. (2) { quality_msg if not is_valid else '' }"
            )

        if errors:
            return create_error_response(
                code=400, message="; ".join(errors), data=data_response_compare
            )

        else:
            similarity = float(
                np.dot(enc1, enc2) / (np.linalg.norm(enc1) * np.linalg.norm(enc2))
            )

            data_response_compare["distance"] = round(similarity, 4)  # similarity
            data_response_compare["match"] = similarity > 0.35  # umbral

            return create_success_response(
                data=data_response_compare,
                message="Images compared successfully",
                code=200,
            )

    except Exception as e:
        print(traceback.format_exc())
        return create_error_response(
            code=500,
            message=f"Error processing images: {str(e)}",
            data=data_response_compare,
        )
