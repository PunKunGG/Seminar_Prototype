# ClassMood AI

ระบบเว็บสำหรับวิเคราะห์พฤติกรรมนักศึกษาในชั้นเรียนจากเว็บแคมหรือไฟล์วิดีโอ โดยใช้ YOLOv8 และ YOLOv8 Pose Estimation

ระบบนี้ออกแบบให้ใช้งานแบบไม่ต้องเชื่อมต่อ CCTV: เริ่มรอบวิเคราะห์ เลือกเว็บแคมหรืออัปโหลดคลิป แล้วให้ระบบวิเคราะห์จนจบคลิปและเปิดรายงานให้อัตโนมัติ

## สิ่งที่ระบบทำได้

- วิเคราะห์พฤติกรรมจากภาพวิดีโอ เช่น ตั้งใจเรียน หลับ ก้มหน้า/โทรศัพท์ และมองออก
- ใช้ได้ทั้งเว็บแคมและไฟล์วิดีโอ
- อัปโหลดคลิปผ่านหน้าเว็บได้โดยตรง
- คลิปวิดีโอจะไม่วนซ้ำ เมื่อคลิปจบ ระบบจะเปิดหน้ารายงานให้อัตโนมัติ
- แสดงกราฟความตั้งใจเรียนและสัดส่วนพฤติกรรมแบบ real time
- ส่งออกรายงานเป็น PDF, Excel, CSV หรือ JSON
- เก็บข้อมูล runtime ไว้เฉพาะเครื่อง ไม่ควร commit ขึ้น repo

## โครงสร้างโปรเจกต์

```text
Seminar_Prototype/
├── backend/
│   ├── server.py              # Flask server และ API หลัก
│   ├── behavior_analyzer.py   # วิเคราะห์ pose และพฤติกรรม
│   ├── detector.py            # ตัวช่วยตรวจจับวัตถุ/คน
│   ├── data/                  # runtime data เช่น stats.json (ignored)
│   ├── test_images/           # รูปทดสอบเก่าหรือ fallback
│   └── video_sources/         # วิดีโอที่อัปโหลดผ่านเว็บ (ignored)
├── dashboard/
│   ├── index.html             # หน้าเว็บหลัก
│   ├── shared.js              # logic ฝั่ง frontend
│   ├── style.css              # style เพิ่มเติม
│   └── asset/                 # รูป/โลโก้
├── requirements.txt
├── .gitignore
└── README.md
```

## สิ่งที่ไม่ควร commit

ไฟล์เหล่านี้เป็นไฟล์ runtime หรือไฟล์ขนาดใหญ่ และถูกใส่ไว้ใน `.gitignore` แล้ว:

- `venv/`, `.venv/`
- `*.pt`, `*.onnx`, `*.weights`
- `backend/video_sources/`
- `backend/data/stats.json`
- `__pycache__/`

ถ้า `backend/data/stats.json` เคยถูก track ไปแล้ว ให้เลิก track ด้วยคำสั่งนี้ครั้งเดียว:

```powershell
git rm --cached -- backend/data/stats.json
```

คำสั่งนี้ไม่ลบไฟล์จริงในเครื่อง แค่บอก Git ว่าไม่ต้องตามไฟล์นี้แล้ว

## การติดตั้งหลัง clone repo

### 1. Clone repo

```bash
git clone <repository-url>
cd Seminar_Prototype
```

### 2. สร้าง virtual environment

Windows:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

ถ้าใช้ CMD:

```cmd
python -m venv venv
venv\Scripts\activate.bat
```

macOS/Linux:

```bash
python -m venv venv
source venv/bin/activate
```

แนะนำให้เช็ก Python ก่อนติดตั้ง dependency:

```bash
python --version
```

โปรเจกต์นี้พัฒนากับ Python 3.11 ถ้าใช้ Python ใหม่มาก ๆ แล้วติดปัญหา dependency ให้ลองใช้ Python 3.10 หรือ 3.11

### 3. ติดตั้ง dependencies

```bash
pip install -r requirements.txt
```

Dependencies หลักอยู่ใน `requirements.txt`:

- Flask
- Flask-CORS
- Ultralytics
- OpenCV
- NumPy

### 4. เตรียมไฟล์โมเดล YOLO

ระบบจะพยายามหาไฟล์โมเดลใน `backend/` และ project root ก่อน ถ้าไม่เจอ Ultralytics จะพยายามดาวน์โหลดให้อัตโนมัติในครั้งแรกที่รัน

ไฟล์ที่ใช้ได้:

- `yolov8s.pt` หรือ `yolov8n.pt` สำหรับตรวจจับคน
- `yolov8s-pose.pt` หรือ `yolov8n-pose.pt` สำหรับวิเคราะห์ท่าทาง

วางไฟล์ไว้ได้ที่:

```text
Seminar_Prototype/
backend/
```

หรือ project root:

```text
Seminar_Prototype/
```

หมายเหตุ: ไฟล์ `.pt` ถูก ignore เพราะมีขนาดใหญ่ จึงต้องดาวน์โหลดหรือคัดลอกมาเองหลัง clone repo

## วิธีรัน

จาก project root:

```bash
cd backend
python server.py
```

จากนั้นเปิดเว็บ:

```text
http://127.0.0.1:5000
```

ถ้าต้องการเปลี่ยน host หรือ port:

Windows PowerShell:

```powershell
$env:CLASSMOOD_HOST="127.0.0.1"
$env:CLASSMOOD_PORT="5000"
python server.py
```

macOS/Linux:

```bash
CLASSMOOD_HOST=127.0.0.1 CLASSMOOD_PORT=5000 python server.py
```

## วิธีใช้งานหน้าเว็บ

1. เปิด `http://127.0.0.1:5000`
2. ตั้งชื่อรอบวิเคราะห์ เช่น `คลิปทดลองช่วงเช้า`
3. กด `เริ่มวิเคราะห์`
4. เลือกแหล่งภาพ
   - `เว็บแคม` สำหรับกล้องที่ต่อกับเครื่อง
   - `อัปโหลดคลิป` สำหรับไฟล์ `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`
5. ระบบจะแสดงภาพวิเคราะห์และกราฟแบบ real time
6. ถ้าเป็นคลิปวิดีโอ เมื่อคลิปจบ ระบบจะเปิดรายงานให้อัตโนมัติ
7. เลือกรูปแบบไฟล์ที่ต้องการดาวน์โหลด หรือปิด modal ถ้ายังไม่ต้องการดาวน์โหลด

## ข้อมูล runtime

ระบบจะสร้าง/แก้ไฟล์เหล่านี้ระหว่างใช้งาน:

- `backend/video_sources/` เก็บวิดีโอที่อัปโหลดผ่านหน้าเว็บ
- `backend/data/stats.json` เก็บสถิติและ activity log ของรอบวิเคราะห์

ไฟล์เหล่านี้เปลี่ยนทุกครั้งที่ทดสอบ จึงไม่ควร commit ขึ้น repo

## API สำคัญ

| Endpoint | Method | ใช้ทำอะไร |
| --- | --- | --- |
| `/` | GET | หน้าเว็บหลัก |
| `/api/videos` | POST | อัปโหลดไฟล์วิดีโอ |
| `/api/sources/<session_id>/<source_id>` | POST | ตั้งแหล่งภาพเป็นเว็บแคมหรือคลิป |
| `/api/sources/<session_id>/<source_id>/status` | GET | เช็กสถานะ source เช่น คลิปจบหรือยัง |
| `/api/stream/<session_id>/<source_id>` | GET | MJPEG stream สำหรับแสดงภาพในเว็บ |
| `/api/data/<session_id>/<source_id>` | GET | จำนวนคนและความมั่นใจจาก detection |
| `/api/behavior/<session_id>/<source_id>` | GET | ผลวิเคราะห์พฤติกรรม |
| `/api/stats/<session_id>` | GET | ข้อมูลย้อนหลังสำหรับกราฟ |
| `/api/activities/<session_id>` | GET | activity log |
| `/api/export/<session_id>` | GET | ข้อมูลรายงาน |
| `/api/alerts` | GET | แจ้งเตือนล่าสุด |

หมายเหตุ: ชื่อ route ยังใช้คำว่า `lab_id` ใน backend บางจุดจากโค้ดเดิม แต่ในหน้าเว็บปัจจุบันเราใช้เป็น `session_id` หรือรหัสรอบวิเคราะห์

## Environment variables

| ชื่อ | ค่าเริ่มต้น | คำอธิบาย |
| --- | --- | --- |
| `CLASSMOOD_HOST` | `127.0.0.1` | host ที่ Flask bind |
| `CLASSMOOD_PORT` | `5000` | port ของ server |
| `CLASSMOOD_DEBUG` | ปิด | เปิด debug mode เมื่อ set เป็น `1` หรือ `true` |
| `CLASSMOOD_ALLOWED_ORIGINS` | `http://127.0.0.1:5000,http://localhost:5000` | CORS origins ที่อนุญาต |
| `CLASSMOOD_VIDEO_DIRS` | `backend/video_sources` | โฟลเดอร์ที่อนุญาตให้ใช้ไฟล์วิดีโอ |
| `CLASSMOOD_MAX_VIDEO_UPLOAD_MB` | `512` | ขนาดอัปโหลดสูงสุดเป็น MB |
| `CLASSMOOD_MAX_WEBCAM_INDEX` | `9` | index เว็บแคมสูงสุดที่อนุญาต |
| `CLASSMOOD_ALLOW_ANY_VIDEO_PATH` | ปิด | ถ้าเปิด จะยอมรับ path วิดีโอนอกโฟลเดอร์ที่กำหนด |
| `CLASSMOOD_ALLOW_REMOTE_SOURCE_CONTROL` | ปิด | ถ้าเปิด จะอนุญาตให้เครื่องอื่นตั้ง source ได้ |

## แก้ปัญหาที่พบบ่อย

### เปิด server แล้วบอกว่าไม่มี Flask

มักเกิดจากยังไม่ได้เข้า virtual environment หรือใช้ Python คนละตัวกับที่ติดตั้ง dependency

```bash
python -m pip install -r requirements.txt
python -c "import flask; print(flask.__version__)"
```

### เปิดหน้าเว็บแล้ว CDN โหลดไม่ได้

หน้าเว็บใช้ CDN สำหรับ TailwindCSS, Chart.js, html2canvas และ jsPDF ถ้าเครื่องไม่มีอินเทอร์เน็ต อาจทำให้ UI หรือ export PDF ทำงานไม่ครบ

### อัปโหลดวิดีโอแล้วไฟล์ใหญ่เกิน

ค่าเริ่มต้นคือ 512 MB ปรับได้ด้วย:

```powershell
$env:CLASSMOOD_MAX_VIDEO_UPLOAD_MB="1024"
```

### เปลี่ยนคลิปแล้วภาพยังค้าง

ให้ refresh หน้าเว็บก่อนหนึ่งครั้ง ถ้ายังเกิดซ้ำ ให้เช็กว่า browser โหลด `dashboard/shared.js` เวอร์ชันล่าสุดแล้ว

## สรุป workflow สำหรับย้ายเครื่อง

1. Clone repo
2. สร้างและ activate virtual environment
3. `pip install -r requirements.txt`
4. เตรียมไฟล์ YOLO `.pt` หรือปล่อยให้ดาวน์โหลดตอนรันครั้งแรก
5. `cd backend`
6. `python server.py`
7. เปิด `http://127.0.0.1:5000`
8. เริ่มรอบวิเคราะห์และทดสอบด้วยเว็บแคมหรือคลิปวิดีโอ

## ผู้พัฒนา

| ชื่อ-นามสกุล                         |  Username                     |
| --------------------------------------- | ------------------------------ |
| `663380026-5 ศิวภาส ภูศรีอ่อน (ข้าวปั้น)` | [PunKunGG](https://github.com/PunKunGG) |
| `663380507-9 นิภาดา ญายะนันท์ (มิ้น)`  | [MintNiphada](https://github.com/MintNiphada) | 

โปรเจกต์สัมมนา - ระบบวิเคราะห์พฤติกรรมนักศึกษาในชั้นเรียนด้วย AI
