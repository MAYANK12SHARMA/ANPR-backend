import cv2
import numpy as np


def deskew_simple(gray, canny_low=50, canny_high=150, angle_limit=20):
    edges = cv2.Canny(gray, canny_low, canny_high)

    lines = cv2.HoughLines(
        edges,
        1,
        np.pi / 180,
        threshold=80
    )

    angle = 0

    if lines is not None:
        angles = []
        for rho, theta in lines[:, 0]:
            deg = (theta * 180.0 / np.pi) - 90
            if -angle_limit < deg < angle_limit:
                angles.append(deg)
        if angles:
            angle = float(np.median(angles))

    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)

    rotated = cv2.warpAffine(
        gray,
        M,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    return rotated


def light_preprocess(img):
    h, w = img.shape[:2]

    if h < 40:
        scale = max(2, int(48 / max(h, 1)))
        img = cv2.resize(
            img,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = deskew_simple(gray)

    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    gray = cv2.addWeighted(gray, 1.2, blur, -0.2, 0)

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)