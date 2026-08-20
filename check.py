import subprocess
import sys

PACKAGES = [
    "torch",
    "torchvision",
    "ultralytics",
    "easyocr",
    "paddlepaddle",
    "paddleocr",
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python",
]


def run(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=False,
    )


print("=" * 70)
print("Installed Packages")
print("=" * 70)

installed = {}

for pkg in PACKAGES:
    r = run([sys.executable, "-m", "pip", "show", pkg])
    if r.returncode == 0:
        installed[pkg] = True
        print(f"✓ {pkg}")
    else:
        installed[pkg] = False

print()

opencv_count = sum(
    installed.get(x, False)
    for x in [
        "opencv-python",
        "opencv-python-headless",
        "opencv-contrib-python",
    ]
)

if opencv_count > 1:
    print("⚠ Multiple OpenCV packages detected.")
    print("Recommended: keep ONLY opencv-contrib-python")
    ans = input("\nUninstall conflicting OpenCV packages? (y/n): ").strip().lower()

    if ans == "y":
        for pkg in ["opencv-python", "opencv-python-headless"]:
            if installed.get(pkg):
                subprocess.call(
                    [sys.executable, "-m", "pip", "uninstall", "-y", pkg]
                )
else:
    print("✓ OpenCV installation looks OK.")

print()

print("=" * 70)
print("Checking torch")
print("=" * 70)

code = """
import torch
print(torch.__version__)
"""

r = run([sys.executable, "-c", code])

if r.returncode == 0:
    print("✓ Torch imports successfully")
    print(r.stdout)
else:
    print("✗ Torch failed")
    print(r.stderr)

print()

print("=" * 70)
print("Checking Ultralytics")
print("=" * 70)

code = """
from ultralytics import YOLO
print("YOLO OK")
"""

r = run([sys.executable, "-c", code])

if r.returncode == 0:
    print("✓ Ultralytics OK")
else:
    print("✗ Ultralytics failed")
    print(r.stderr)

print()

print("=" * 70)
print("Checking EasyOCR")
print("=" * 70)

code = """
import easyocr
print("EasyOCR OK")
"""

r = run([sys.executable, "-c", code])

if r.returncode == 0:
    print("✓ EasyOCR OK")
else:
    print("✗ EasyOCR failed")
    print(r.stderr)

print()

print("=" * 70)
print("Running pip check")
print("=" * 70)

subprocess.call([sys.executable, "-m", "pip", "check"])

print()
print("=" * 70)
print("Done")
print("=" * 70)