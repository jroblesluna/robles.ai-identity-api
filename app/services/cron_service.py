import httpx
from datetime import datetime, timezone

from app.services import store
from app.services.recognition_service import (
    compare_verify_faces,
    decode_base64_to_cv2,
    encode_cv2_to_base64,
)


async def run_cron_verify_id():
    try:
        results_list = store.list_pending()

        if len(results_list) == 0:
            print("No pending requests found.")
            return {"message": "No pending requests found."}

        for data in results_list:
            request_id = data["id"]
            print(f"Starting execution for the request: {request_id}")
            store.update_request(request_id, {"status": "started"})

            input_data = data.get("data", {}).get("input", {})
            face_image_b64 = input_data.get("faceImageBase64")
            card_image_b64 = input_data.get("cardIdImageBase64")
            callback = input_data.get("callback")

            # Initial output structure (mirrors the previous Firestore shape).
            initial_output = {
                "CardImageCV2": "pending",
                "FaceImageCV2": "pending",
                "CardLandMarksImage": "pending",
                "FaceLandMarksImage": "pending",
                "distance": None,
                "result_match": None,
            }
            store.update_request(request_id, {"data.output": initial_output})

            # Decode the base64 input images (was: download from Storage URL).
            response_card_image = decode_base64_to_cv2(card_image_b64)
            if response_card_image.get("success") is False:
                store.update_request(
                    request_id,
                    {
                        "message": "Error loading card image - " + response_card_image.get("message"),
                        "success": False,
                        "status": "failed",
                    },
                )
                continue

            response_face_image = decode_base64_to_cv2(face_image_b64)
            if response_face_image.get("success") is False:
                store.update_request(
                    request_id,
                    {
                        "message": "Error loading face image - " + response_face_image.get("message"),
                        "success": False,
                        "status": "failed",
                    },
                )
                continue

            image_card = response_card_image.get("data")
            face_card = response_face_image.get("data")

            response_matched = compare_verify_faces(image_card, face_card)

            found_errors = False
            text_errors = []

            if response_matched.get("success") is False:
                store.update_request(
                    request_id,
                    {
                        "message": "Error comparing images - " + response_matched.get("message"),
                        "success": False,
                        "status": "failed",
                    },
                )
                found_errors = True
                text_errors.append(response_matched.get("message"))

            data_compare = response_matched.get("data")

            if response_matched.get("success") is True:
                store.update_request(
                    request_id,
                    {
                        "data.output.distance": data_compare.get("distance"),
                        "data.output.result_match": bool(data_compare.get("match")),
                        "message": "Identity successfully compared",
                        "status": "partially_completed",
                    },
                )

            # Fire the callback if one was provided (best-effort).
            if callback:
                payload = {
                    "request_id": request_id,
                    "success": response_matched.get("success"),
                    "message": response_matched.get("message"),
                    "result_match": (
                        bool(data_compare.get("match"))
                        if data_compare and data_compare.get("match") is not None
                        else None
                    ),
                    "distance": data_compare.get("distance") if data_compare else None,
                }
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.post(callback, json=payload)
                        resp.raise_for_status()
                    except Exception as e:
                        found_errors = True
                        print(f"Error calling callback url - {callback} : {e}")
                        text_errors.append(f"Error calling callback url - {callback} : {e}")

            if data_compare is None:
                # Comparison produced nothing usable; nothing else to encode.
                store.update_request(
                    request_id,
                    {
                        "status": "completed_with_errors",
                        "success": True,
                        "message": "Request processed with errors. - Error(s): " + ", ".join(text_errors),
                    },
                )
                continue

            # Encode the 4 processed images as base64 data-URIs (was: upload to
            # Storage + save URL). Thumbnails keep the payload small.
            store.update_request(
                request_id,
                {"data.output.CardImageCV2": encode_cv2_to_base64(data_compare.get("CardImageCV2"))},
            )
            store.update_request(
                request_id,
                {"data.output.FaceImageCV2": encode_cv2_to_base64(data_compare.get("FaceImageCV2"))},
            )
            card_lm = encode_cv2_to_base64(data_compare.get("CardLandMarksImage"))
            store.update_request(
                request_id, {"data.output.CardLandMarksImage": card_lm if card_lm else "failed"}
            )
            face_lm = encode_cv2_to_base64(data_compare.get("FaceLandMarksImage"))
            store.update_request(
                request_id, {"data.output.FaceLandMarksImage": face_lm if face_lm else "failed"}
            )

            if found_errors:
                store.update_request(
                    request_id,
                    {
                        "status": "completed_with_errors",
                        "success": True,
                        "message": "Request processed successfully but with errors. - Error(s): " + ", ".join(text_errors),
                    },
                )
            else:
                store.update_request(
                    request_id,
                    {
                        "status": "completed",
                        "success": True,
                        "message": "Request processed successfully.",
                    },
                )

        return {"message": "Pending requests updated successfully."}

    except Exception as e:
        print(f"Error processing pending requests: {e}")
        return {"error": str(e)}
