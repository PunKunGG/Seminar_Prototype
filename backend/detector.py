from ultralytics import YOLO
import cv2
import json
import os
import sys

# ✅ รองรับ path จาก argument ถ้าอยากทดสอบหลายภาพ
if len(sys.argv) > 1:
    image_path = sys.argv[1]
else:
    # path เริ่มต้น (เปลี่ยนให้ตรงกับที่เก็บ test_images)
    image_path = os.path.join(os.path.dirname(__file__), "test_images", "9226_1.png")

if not os.path.exists(image_path):
    print(json.dumps({"error": f"Image not found: {image_path}"}))
    sys.exit(1)

# โหลดโมเดล YOLO (เฉพาะคน)
base_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(base_dir, os.pardir))
model_path = next(
    (
        path
        for path in (
            os.path.join(base_dir, "yolov8n.pt"),
            os.path.join(project_root, "yolov8n.pt"),
        )
        if os.path.exists(path)
    ),
    "yolov8n.pt",
)
model = YOLO(model_path)
model.classes = [0]  # class 0 = person

# อ่านภาพและตรวจจับ
results = model(image_path)
boxes = results[0].boxes

num_people = len(boxes)
confidences = [float(box.conf[0]) for box in boxes]
avg_conf = round(sum(confidences) / len(confidences) * 100, 2) if confidences else 0

# ✅ ส่งออก JSON ให้ backend อื่นอ่านได้
output = {
    "students": num_people,
    "computers": 30,  # สมมุติไว้ก่อน
    "usage": f"{int((num_people/30)*100)}%",
    "avg_confidence": f"{avg_conf}%",
    "image": os.path.basename(image_path)
}

print(json.dumps(output, ensure_ascii=False, indent=2))
