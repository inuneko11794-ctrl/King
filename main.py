from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
from datetime import datetime
import easyocr
import io
from PIL import Image
import numpy as np

app = FastAPI()
reader = easyocr.Reader(['ja', 'en'], gpu=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
    conn = sqlite3.connect("keiba_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS races (id INTEGER PRIMARY KEY AUTOINCREMENT, race_date TEXT, race_name TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS horses (id INTEGER PRIMARY KEY AUTOINCREMENT, race_id INTEGER, horse_number INTEGER, horse_name TEXT, popularity INTEGER, sp REAL, ag REAL, s REAL, a REAL, sa REAL, total_score REAL, actual_rank INTEGER, FOREIGN KEY (race_id) REFERENCES races(id))''')
    conn.commit()
    conn.close()

def save_race(race_name, horses_data):
    conn = sqlite3.connect("keiba_data.db")
    c = conn.cursor()
    c.execute("INSERT INTO races (race_name, created_at) VALUES (?, ?)", (race_name, datetime.now().isoformat()))
    race_id = c.lastrowid
    for h in horses_data:
        c.execute('''INSERT INTO horses (race_id, horse_number, horse_name, popularity, sp, ag, s, a, sa, total_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (race_id, h['number'], h['name'], h['pop'], h['sp'], h['ag'], h['s'], h['a'], h['sa'], h['score']))
    conn.commit()
    conn.close()
    return race_id

def calculate_score(horse):
    score = horse['sa'] * 0.4 + horse['ag'] * 0.25 + horse['sp'] * 0.2 + horse['s'] * 0.1 + (20 - horse['pop']) * 0.5
    return round(score, 1)

@app.on_event("startup")
def startup_event():
    init_db()

@app.post("/api/analyze")
async def analyze_image(file: UploadFile = File(...)):
    contents = await file.read()
    image = Image.open(io.BytesIO(contents))
    results = reader.readtext(np.array(image), detail=1)
    
    lines = {}
    for bbox, text, conf in results:
        y = int(bbox[0][1] // 15) * 15
        x = int(bbox[0][0])
        if y not in lines:
            lines[y] = []
        lines[y].append((x, text, conf))
    
    parsed_horses = []
    for y in sorted(lines.keys()):
        row = sorted(lines[y], key=lambda x: x[0])
        texts = [item[1] for item in row]
        if len(texts) < 8 or not texts[0].isdigit():
            continue
        try:
            horse_name = texts[1].replace("2牡", "").replace("2牝", "").replace("2せん", "").replace("□", "").replace("口", "").strip()
            def safe_num(val):
                c_val = str(val).replace('O', '0').replace('o', '0').replace(' ', '')
                return float(c_val) if c_val.replace('.', '', 1).isdigit() else 0.0
            
            parsed_horses.append({
                "number": int(texts[0]), "name": horse_name,
                "pop": int(safe_num(texts[2])), "sp": safe_num(texts[3]),
                "ag": safe_num(texts[4]), "s": safe_num(texts[5]),
                "a": safe_num(texts[6]), "sa": safe_num(texts[7])
            })
        except Exception:
            continue

    for horse in parsed_horses:
        horse['score'] = calculate_score(horse)
        
    race_name = f"自動解析レース_{datetime.now().strftime('%Y%m%d%H%M')}"
    race_id = save_race(race_name, parsed_horses)
    return JSONResponse(content={"race_id": race_id, "race_name": race_name, "horses": parsed_horses})

# ここでフロントエンドのHTMLを配信
app.mount("/", StaticFiles(directory="static", html=True), name="static")
