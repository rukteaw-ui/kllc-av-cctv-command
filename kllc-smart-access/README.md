# KLLC Smart Access Lite

> ระบบตรวจจับและบันทึกประวัติการเข้า-ออกด้วยใบหน้า (Face Recognition Access Log) สำหรับ **สำนักการเรียนรู้ตลอดชีวิต (KLLC) สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง**  
> เชื่อมต่อตรงกับเครื่องบันทึกภาพ **Hikvision NVR DeepinMind Pro `iDS-7716NXI-M4/X`** ผ่านโปรโตคอล **ISAPI** (HTTP Digest Authentication) รันบน Windows PC ได้ทันทีโดยไม่ต้องติดตั้ง Docker หรือ Linux

---

## 🚀 ฟีเจอร์หลัก (Key Features)

1. **ดูสด & ผลเทียบใบหน้าเรียลไทม์ (Live Monitor):**
   - รับสตรีมเหตุการณ์จาก NVR ผ่าน `/ISAPI/Event/notification/alertStream` แบบ Long-lived HTTP Stream พร้อมระบบ Auto-Reconnect
   - ดันการ์ดผลเทียบใบหน้าขึ้นหน้าจอทันทีผ่าน WebSocket
   - รองรับกล้อง 4 จุดหลัก:
     - `D1`: โซน Co-working Space
     - `D2`: ทางเข้าหลัก อาคาร KLLC (Main Entrance)
     - `D3`: ประตูทางเชื่อม Sky Walk Door
     - `D9`: เคาน์เตอร์ประชาสัมพันธ์หลัก (Main Information)
   - แยกสีชัดเจน: **ระบุตัวตนได้ (`MATCHED`)** แถบสีเขียว พร้อมชื่อ รหัสบุคคล สังกัด และ % ความเหมือน | **ไม่ทราบตัวตน (`UNKNOWN`)** แถบสีเทา
   - ระบบเสียงแจ้งเตือนสังเคราะห์ผ่าน Web Audio API (ไม่ต้องพึ่งพาไฟล์เสียงภายนอก)

2. **ประวัติการเข้า-ออก & ค้นหาอัจฉริยะ (Access History & Search):**
   - แถบสรุปสถิติประจำวัน: ยอดรวม, ระบุตัวตนได้, ไม่ทราบตัวตน, จำนวนคนไม่ซ้ำ, อัตราการรู้จำ (Match Rate %)
   - ฟิลเตอร์ตามช่วงวันที่ (วันนี้, เมื่อวาน, 7 วัน, กำหนดเอง), ค้นหาชื่อ/รหัส, กรองจุดกล้อง, กรองสังกัด
   - **ตัวเลือกยุบแถวไม่ทราบตัวตนที่ติดกัน (Collapse Consecutive Unknowns):** กรองเฟรมซ้ำกรณีบุคคลภายนอกเดินผ่านกล้องแล้วจับติดกันหลายช็อต
   - **ส่งออกรายงาน:** ส่งออก Excel (`.xlsx`) จัดรูปแบบพร้อมช่องสีสวยงาม และ CSV (UTF-8 BOM ภาษาไทยไม่เพี้ยน)

3. **คลังรายชื่อบุคลากร (Personnel Library):**
   - ซิงก์รายชื่อจาก NVR โดยตรงจากคลัง `KLLC STAFF` และ `KLLC Access` ผ่าน `/ISAPI/Intelligent/FDLib`
   - ตรวจสอบสถานะความยินยอมการใช้งานข้อมูลตามแนวทาง PDPA (`CONSENTED`)
   - ไม่บันทึกไฟล์ภาพ Snapshot ลงฐานข้อมูลเพื่อความปลอดภัยและปฏิบัติตามมาตรฐาน PDPA

4. **ความปลอดภัยสูง (Strict Safe-Read Guardrail):**
   - อนุญาตเฉพาะคำสั่งอ่านข้อมูลและรับ Event Stream เท่านั้น
   - มีกลไกบล็อกคำสั่งที่มีความเสี่ยงต่อระบบ NVR 100% (ห้ามแก้ไขระบบ, รีบูต, ฟอร์แมต หรือดาวน์โหลดวิดีโอย้อนหลัง)

---

## 📁 โครงสร้างโปรเจกต์

```text
kllc-smart-access/
├── .env.example            # ตัวอย่างค่าตั้งค่า NVR (IP, Port, Username, Password)
├── requirements.txt        # รายการ Python dependencies (FastAPI, uvicorn, httpx, aiosqlite, openpyxl)
├── start_kllc_access.bat   # สคริปต์คลิกเดียวสำหรับรันบน Windows (สร้าง venv + รันเซิร์ฟเวอร์ + เปิดเบราว์เซอร์)
├── start_kllc_access.sh    # สคริปต์สำหรับรันบน Linux/macOS
├── app/
│   ├── main.py             # FastAPI App, Lifespan Handler & WebSocket Broadcaster
│   ├── config.py           # ตัวแปรระบบ, การแมปช่องกล้อง D1-D9 และ Safe Endpoints
│   ├── database.py         # ฐานข้อมูล SQLite (persons, access_events, cameras)
│   ├── isapi_client.py     # ตัวเชื่อมต่อ Hikvision ISAPI Digest Auth & alertStream
│   ├── parser.py           # ตัวแกะข้อมูล XML/JSON จาก alertStream
│   └── routes/
│       ├── api.py          # REST APIs (ประวัติ, สถิติ, ซิงก์ NVR, ส่งออก Excel/CSV)
│       └── ws.py           # WebSocket Endpoint สำหรับส่งข้อมูลเรียลไทม์
└── static/
    ├── index.html          # Executive Dashboard SPA (Tailwind CSS Dark Theme)
    └── app.js              # WebSocket Client, ฟิลเตอร์ข้อมูล, WebAudio Chime
```

---

## 🛠️ วิธีการติดตั้งและเริ่มใช้งานบน Windows

### 1. ความต้องการของระบบ
* Windows 10 หรือ Windows 11
* Python 3.11 หรือสูงกว่า (ดาวน์โหลดจาก [python.org](https://www.python.org/downloads/) และติ๊กเลือก **"Add Python to PATH"**)
* อยู่ในวงแลน (LAN/VLAN) เดียวกับเครื่องบันทึกภาพ NVR DeepinMind

### 2. ตั้งค่าการเชื่อมต่อ NVR
เปิดไฟล์ `.env` (หากยังไม่มี ให้คัดลอกมาจาก `.env.example`) แล้วระบุข้อมูล NVR:
```ini
NVR_IP=192.168.1.100       # ไอพีของเครื่อง NVR
NVR_PORT=80               # พอร์ต HTTP/ISAPI ของ NVR
NVR_USER=admin            # บัญชีผู้ใช้ NVR
NVR_PASS=YourNvrPassword! # รหัสผ่าน NVR
```

### 3. รันระบบ
ดับเบิลคลิกที่ไฟล์ **`start_kllc_access.bat`**  
ระบบจะดำเนินการให้โดยอัตโนมัติ:
1. สร้าง Python Virtual Environment (`.venv`)
2. ติดตั้งไลบรารีที่จำเป็น
3. เปิดหน้าต่างเบราว์เซอร์ไปยัง `http://localhost:8000`
4. เริ่มเชื่อมต่อ Hikvision NVR และรอรับผลสแกนใบหน้าทันที
