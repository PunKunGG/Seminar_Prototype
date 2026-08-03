# ClassMood AI

ระบบเว็บสำหรับวิเคราะห์พฤติกรรมนักศึกษาในชั้นเรียนจากเว็บแคมหรือไฟล์วิดีโอ โดยใช้ YOLOv8 และ YOLOv8 Pose Estimation

ระบบนี้ออกแบบให้ใช้งานแบบไม่ต้องเชื่อมต่อ CCTV: เริ่มรอบวิเคราะห์ เลือกเว็บแคมหรืออัปโหลดคลิป แล้วให้ระบบวิเคราะห์จนจบคลิปและเปิดรายงานให้อัตโนมัติ

## สิ่งที่ระบบทำได้

- วิเคราะห์พฤติกรรมจากภาพวิดีโอ เช่น ตั้งใจเรียน หลับ ก้มหน้า/โทรศัพท์ ยกมือ และยืน/ลุกจากที่นั่ง
- ติดตามบุคคลแบบไม่ระบุตัวตนด้วย `ID 1`, `ID 2`, ... ภายในแต่ละรอบวิเคราะห์
- นับเหตุการณ์และเวลาของพฤติกรรมแยกราย ID โดยมีช่วงยืนยันพฤติกรรมเพื่อลดการนับซ้ำทุกเฟรม
- เก็บภาพอ้างอิงของแต่ละ ID และภาพหลักฐานเมื่อพฤติกรรมสำคัญผ่านเกณฑ์ยืนยัน
- สรุปเปอร์เซ็นต์ความตั้งใจรายบุคคลและแบ่งรายงานเป็นช่วงละ 1 ชั่วโมง
- แยกข้อมูลตามห้อง รายวิชา และคาบเรียนด้วยฐานข้อมูล SQLite
- ใช้ได้ทั้งเว็บแคมและไฟล์วิดีโอ
- อัปโหลดคลิปผ่านหน้าเว็บได้โดยตรง
- คลิปวิดีโอจะไม่วนซ้ำ เมื่อคลิปจบ ระบบจะเปิดหน้ารายงานให้อัตโนมัติ
- แสดงกราฟความตั้งใจเรียนและสัดส่วนพฤติกรรมแบบ real time
- ส่งออกรายงานเป็น PDF, Excel, CSV หรือ JSON
- ล็อกอินบัญชีอาจารย์ด้วย Supabase Auth ก่อนเรียก API หรือเปิดวิดีโอสตรีม
- เก็บข้อมูล runtime ไว้เฉพาะเครื่อง ไม่ควร commit ขึ้น repo

## โครงสร้างโปรเจกต์

```text
Seminar_Prototype/
├── backend/
│   ├── server.py              # ประกอบ services, จัดการ runtime state และ API หลัก
│   ├── app_config.py          # อ่านและตรวจค่าตั้งจาก environment
│   ├── auth_service.py        # ตรวจ Supabase access token และดูแล session secret
│   ├── video_source_policy.py # ตรวจ webcam/path และสร้างชื่อไฟล์อัปโหลดอย่างปลอดภัย
│   ├── behavior_analyzer.py   # วิเคราะห์ pose และพฤติกรรม
│   ├── person_tracking.py      # ติดตาม ID และรวมเหตุการณ์พฤติกรรม
│   ├── session_database.py     # จัดเก็บห้อง วิชา คาบ และผลราย ID ด้วย SQLite
│   ├── video_sampling.py       # สุ่มช่วงและรวมผลสำหรับคลิปยาว
│   ├── evidence_store.py       # crop และจัดเก็บภาพหลักฐานของแต่ละ ID
│   ├── detector.py            # ตัวช่วยตรวจจับวัตถุ/คน
│   ├── data/                  # stats, SQLite และภาพหลักฐาน (ignored)
│   ├── test_images/           # รูปทดสอบเก่าหรือ fallback
│   └── video_sources/         # วิดีโอที่อัปโหลดผ่านเว็บ (ignored)
├── dashboard/
│   ├── index.html             # หน้าเว็บหลัก
│   ├── auth.js                # Login/Logout และแลก token เป็น Flask session
│   ├── shared.js              # session, live view, chart และ report data
│   ├── report-pdf.js          # สร้าง PDF และจัดการการแบ่งหน้า
│   ├── style.css              # style เพิ่มเติม
│   └── asset/                 # รูป/โลโก้
├── requirements.txt
├── supabase/migrations/       # schema, RLS policies และ Storage buckets
├── tests/
├── .gitignore
└── README.md
```

## สิ่งที่ไม่ควร commit

ไฟล์เหล่านี้เป็นไฟล์ runtime หรือไฟล์ขนาดใหญ่ และถูกใส่ไว้ใน `.gitignore` แล้ว:

- `venv/`, `.venv/`
- `*.pt`, `*.onnx`, `*.weights`
- `backend/video_sources/`
- `backend/data/stats.json`
- `backend/data/classmood.db*`
- `backend/data/evidence/`
- `backend/data/session_secret`
- `.env`, `.env.local`
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
- NumPy 1.x สำหรับ OpenCV 4.9
- PyTorch 2.5.1 และ Torchvision 0.20.1 สำหรับ checkpoint ของ YOLO รุ่นปัจจุบัน

เวอร์ชัน NumPy, PyTorch และ Torchvision ถูกจำกัดไว้ใน `requirements.txt` โดยตั้งใจ การปล่อยให้ pip เลือกรุ่นล่าสุดอาจทำให้ OpenCV import ไม่ได้หรือ Ultralytics 8.1 โหลดไฟล์โมเดลเดิมไม่สำเร็จ

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

### 5. ตั้งค่า Supabase Auth

คัดลอกไฟล์ตัวอย่างเป็น `.env`:

```powershell
Copy-Item .env.example .env
```

ใส่ค่า `SUPABASE_URL` และ `SUPABASE_PUBLISHABLE_KEY` จากหน้า Supabase
`Project Settings > API Keys` ห้ามนำ Secret key, service-role key หรือรหัสผ่านฐานข้อมูลมาใส่ในไฟล์นี้

จากนั้นไปที่ `Authentication > Users` ใน Supabase แล้วสร้างบัญชีอาจารย์อย่างน้อยหนึ่งบัญชี หน้า ClassMood ไม่มีปุ่มสมัครสมาชิกสาธารณะ ผู้ดูแลจึงเป็นคนกำหนดว่าใครเข้าใช้งานได้
สำหรับโปรเจกต์ Supabase ใหม่ ให้ไปที่ `Authentication > Sign In / Providers` แล้วปิด `Allow new users to sign up` ด้วย เพื่อป้องกันการสมัครผ่าน Auth API โดยตรง

ค่าที่ควรใช้ตอน deploy ผ่าน HTTPS:

```dotenv
CLASSMOOD_REQUIRE_AUTH=true
CLASSMOOD_SESSION_COOKIE_SECURE=true
CLASSMOOD_SESSION_SECRET=<ค่าสุ่มคงที่อย่างน้อย 32 ตัวอักษร>
```

บนเครื่อง local ให้ `CLASSMOOD_SESSION_COOKIE_SECURE=false` และปล่อย `CLASSMOOD_SESSION_SECRET` ว่างได้ ระบบจะสร้างค่าคงที่ไว้ที่ `backend/data/session_secret` ซึ่ง Git ignore ไว้แล้ว

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

1. เปิด `http://127.0.0.1:5000` และเข้าสู่ระบบด้วยบัญชีอาจารย์ใน Supabase
2. ตั้งชื่อรอบ รายวิชา ห้องเรียน และเวลาเริ่มบันทึก
3. กด `เริ่มวิเคราะห์`
4. เลือกแหล่งภาพ
   - `เว็บแคม` สำหรับกล้องที่ต่อกับเครื่อง
   - `อัปโหลดคลิป` สำหรับไฟล์ `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`
5. ระบบจะแสดงภาพวิเคราะห์ กราฟ และตารางราย ID แบบ real time
6. ถ้าเป็นคลิปวิดีโอ เมื่อคลิปจบ ระบบจะเปิดรายงานให้อัตโนมัติ
7. เลือกรูปแบบไฟล์ที่ต้องการดาวน์โหลด หรือปิด modal ถ้ายังไม่ต้องการดาวน์โหลด

## การวิเคราะห์คลิปยาว

คลิปที่ยาวตั้งแต่ 30 นาทีขึ้นไปจะเข้าโหมดวิเคราะห์แบบสุ่มช่วงอัตโนมัติ เพื่อให้รองรับวิดีโอการเรียน 3-4 ชั่วโมงโดยไม่ต้องรัน AI ทุกเฟรม:

- วิเคราะห์ช่วง 10 วินาทีแรกของทุก 1 นาที
- ใช้ 2 เฟรมต่อวินาทีภายในช่วงที่เลือก หรือสูงสุด 20 เฟรมต่อหนึ่งนาทีของคลิป
- รวมผลหลายเฟรมเป็นสถิติหนึ่งจุดต่อหนึ่งนาที
- แสดงเปอร์เซ็นต์และตำแหน่งเวลาในคลิประหว่างประมวลผล
- เปิดรายงานอัตโนมัติเมื่อประมวลผลครบทุกช่วงเหมือนคลิปสั้น
- รายงานบนหน้าเว็บและ PDF สรุปคลิปยาวเป็นช่วงละ 10 นาที ส่วน CSV/Excel เก็บรายละเอียดรายนาที
- ผลรายบุคคลแบ่งตามเวลานาฬิกาช่วงละ 1 ชั่วโมง โดยอ้างอิงช่อง `เวลาเริ่มบันทึก`
- รายงานแนบภาพอ้างอิงของ ID และภาพเหตุการณ์สำคัญ โดยค่าเริ่มต้นจำกัดไม่เกิน 50 เหตุการณ์ต่อ ID

โหมดนี้ประมวลผลไฟล์โดยกระโดดไปยังช่วงตัวอย่าง จึงไม่ต้องรอเท่าความยาวจริงของวิดีโอ เวลาที่ใช้จริงขึ้นอยู่กับ CPU/GPU จำนวนคนในภาพ และโมเดล pose ที่ติดตั้ง
เปอร์เซ็นต์ราย ID ของคลิปยาวคำนวณจากเฟรมตัวอย่างที่ตรวจจริง ส่วน `เวลาที่ตรวจพบ` จะแสดงเวลารวมของตัวอย่าง ไม่ใช่การคาดเดาเวลาระหว่างช่วงที่ข้ามไป

ข้อจำกัด: ค่าอัปโหลดเริ่มต้นยังอยู่ที่ 512 MB หากไฟล์จากโทรศัพท์มีขนาดใหญ่กว่านี้ แนะนำให้บีบอัดวิดีโอหรือปรับ `CLASSMOOD_MAX_VIDEO_UPLOAD_MB` โดยตรวจสอบพื้นที่ว่างในเครื่องก่อน

## ข้อมูล runtime

ระบบจะสร้าง/แก้ไฟล์เหล่านี้ระหว่างใช้งาน:

- `backend/video_sources/` เก็บวิดีโอที่อัปโหลดผ่านหน้าเว็บ
- `backend/data/stats.json` เก็บสถิติและ activity log ของรอบวิเคราะห์
- `backend/data/classmood.db` เก็บห้อง รายวิชา คาบ ID ชั่วคราว เหตุการณ์ และผลรวมรายนาที
- `backend/data/evidence/` เก็บภาพอ้างอิงและภาพเหตุการณ์ที่ใช้ในรายงาน
- `backend/data/session_secret` ใช้ลงลายเซ็น session cookie บนเครื่อง local

ไฟล์เหล่านี้เปลี่ยนทุกครั้งที่ทดสอบ จึงไม่ควร commit ขึ้น repo
SQLite จะถูกสร้างให้อัตโนมัติเมื่อเปิด server ครั้งแรก ไม่ต้องติดตั้ง database server เพิ่ม
ถ้าต้องการเริ่มข้อมูลใหม่ให้ปิด server ก่อน แล้วจึงลบ `backend/data/classmood.db` และไฟล์ที่ขึ้นต้นด้วยชื่อเดียวกัน

## API สำคัญ

| Endpoint | Method | ใช้ทำอะไร |
| --- | --- | --- |
| `/` | GET | หน้าเว็บหลัก |
| `/api/config` | GET | ค่า public ที่หน้าเว็บต้องใช้เริ่ม Supabase Auth |
| `/api/auth/session` | POST | ตรวจ Supabase token และสร้าง HttpOnly session cookie |
| `/api/auth/me` | GET | ผู้ใช้ที่ล็อกอินอยู่ |
| `/api/auth/logout` | POST | ล้าง session cookie |
| `/api/videos` | POST | อัปโหลดไฟล์วิดีโอ |
| `/api/sources/<session_id>/<source_id>` | POST | ตั้งแหล่งภาพเป็นเว็บแคมหรือคลิป |
| `/api/sources/<session_id>/<source_id>/status` | GET | เช็กสถานะ source เช่น คลิปจบหรือยัง |
| `/api/stream/<session_id>/<source_id>` | GET | MJPEG stream สำหรับแสดงภาพในเว็บ |
| `/api/annotated-stream/<session_id>/<source_id>` | GET | MJPEG stream ที่วาดกรอบตรวจจับหรือ pose annotation |
| `/api/data/<session_id>/<source_id>` | GET | จำนวนคนและความมั่นใจจาก detection |
| `/api/behavior/<session_id>/<source_id>` | GET | ผลวิเคราะห์พฤติกรรม |
| `/api/sessions/<session_id>/tracks` | GET | ผลราย ID และรายช่วงเวลา ค่าเริ่มต้นช่วงละ 1 ชั่วโมง |
| `/api/evidence/<session_id>/<filename>` | GET | ภาพหลักฐานของรอบวิเคราะห์ ใช้ได้จากเครื่อง local ตามค่าเริ่มต้น |
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
| `CLASSMOOD_ANNOTATED_STREAM_FPS` | `5` | เฟรมเรตของ stream ที่วาดกรอบตรวจจับ จำกัดสูงสุดที่ 5 |
| `CLASSMOOD_MAX_HISTORY` | `480` | จำนวนจุดสถิติสูงสุดต่อรอบ เพียงพอสำหรับคลิปยาว 8 ชั่วโมงเมื่อสรุปทุก 1 นาที |
| `CLASSMOOD_LONG_VIDEO_THRESHOLD_SECONDS` | `1800` | ความยาวขั้นต่ำที่เปิดโหมดคลิปยาว |
| `CLASSMOOD_LONG_VIDEO_SAMPLE_INTERVAL_SECONDS` | `60` | ระยะห่างระหว่างช่วงตัวอย่าง |
| `CLASSMOOD_LONG_VIDEO_SAMPLE_WINDOW_SECONDS` | `10` | ความยาวของช่วงที่นำมาวิเคราะห์ในแต่ละรอบ |
| `CLASSMOOD_LONG_VIDEO_SAMPLE_FPS` | `2` | จำนวนเฟรมต่อวินาทีภายในช่วงตัวอย่าง จำกัดสูงสุดที่ 5 |
| `CLASSMOOD_DATABASE_PATH` | `backend/data/classmood.db` | ตำแหน่งฐานข้อมูล SQLite |
| `CLASSMOOD_TRACK_MAX_MISSING_SECONDS` | `4` | เวลาที่ ID แบบ real-time หายจากภาพได้ก่อนปิด track |
| `CLASSMOOD_TRACKING_DB_WRITE_INTERVAL` | `2` | ระยะห่างขั้นต่ำระหว่างการบันทึก tracking ลง SQLite |
| `CLASSMOOD_REALTIME_STATS_INTERVAL` | `4` | ระยะห่างการบันทึกสถิติรวมในโหมด real-time |
| `CLASSMOOD_EVIDENCE_ENABLED` | เปิด | เปิดการบันทึกภาพหลักฐาน ตั้งเป็น `0` หรือ `false` เพื่อปิด |
| `CLASSMOOD_EVIDENCE_DIR` | `backend/data/evidence` | โฟลเดอร์เก็บภาพหลักฐาน |
| `CLASSMOOD_EVIDENCE_BEHAVIORS` | `sleeping,looking_down,hand_raised,standing` | พฤติกรรมที่ต้องเก็บภาพเมื่อเริ่มเหตุการณ์ |
| `CLASSMOOD_MAX_EVIDENCE_PER_TRACK` | `50` | จำนวนภาพเหตุการณ์สูงสุดต่อ ID ไม่รวมภาพอ้างอิง |
| `CLASSMOOD_EVIDENCE_JPEG_QUALITY` | `86` | คุณภาพ JPEG ของภาพหลักฐาน |
| `CLASSMOOD_EVIDENCE_MAX_DIMENSION` | `900` | ความกว้างหรือความสูงสูงสุดของภาพหลักฐาน |
| `CLASSMOOD_ALLOW_ANY_VIDEO_PATH` | ปิด | ถ้าเปิด จะยอมรับ path วิดีโอนอกโฟลเดอร์ที่กำหนด |
| `CLASSMOOD_ALLOW_REMOTE_SOURCE_CONTROL` | ปิด | ถ้าเปิด จะอนุญาตให้เครื่องอื่นตั้ง source ได้ |

## แก้ปัญหาที่พบบ่อย

### ID เปลี่ยนหรือสลับคน

ID เป็นรหัสชั่วคราวของรอบวิเคราะห์ ไม่ใช่รหัสนักศึกษา ระบบจับคู่จากตำแหน่งและการซ้อนทับของกรอบ หากบุคคลถูกบัง เดินตัดกัน หรือหายจากภาพนาน ID อาจเปลี่ยนได้ ควรใช้กล้องมุมคงที่ เห็นโต๊ะชัด และลดการแพนกล้องระหว่างคาบ

### การจัดการภาพหลักฐาน

ภาพหลักฐานอาจมองเห็นบุคคลในชั้นเรียน ควรกำหนดผู้ที่เข้าถึงได้ ระยะเวลาเก็บรักษา และการลบข้อมูลหลังหมดความจำเป็น ระบบปัจจุบันใช้ภาพเพื่ออ้างอิง ID ภายในคาบเท่านั้น ไม่ได้จดจำใบหน้าหรือระบุตัวบุคคลข้ามคาบ

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
