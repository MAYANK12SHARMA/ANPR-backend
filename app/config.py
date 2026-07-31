import os

OCR_ENGINE = os.getenv("OCR_ENGINE", "paddleocr")

USE_GPU = os.getenv("OCR_USE_GPU", "true").lower() == "true"

PADDLE_OCR_MODEL_DIR = os.getenv("PADDLE_OCR_MODEL_DIR", r"D:\temp\ANRP Project\PaddleOCR Fine Tune\custom_plate_inference")
