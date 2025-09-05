# server.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from vosk import Model, KaldiRecognizer
import wave, os, sqlite3, uuid, re
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

app = FastAPI()

# ----------------- CORS -----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- CONFIG -----------------
VOSK_MODEL_PATH = "models/vosk-model-en-us-0.22-lgraph"
DB_PATH = "signs.db"
TEMP_DIR = "temp_audio"

os.makedirs(TEMP_DIR, exist_ok=True)

# Load Vosk model
model_vosk = Model(VOSK_MODEL_PATH)

# Load FLAN-T5-LARGE model for grammar correction
MODEL_NAME = "google/flan-t5-large"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model_flan = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

# ----------------- SPEECH RECOGNITION -----------------
@app.post("/recognize/")
async def recognize(file: UploadFile = File(...)):
    try:
        temp_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}.wav")
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        wf = wave.open(temp_path, "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            wf.close()
            os.remove(temp_path)
            return JSONResponse({"error": "Audio must be WAV PCM mono"}, status_code=400)

        rec = KaldiRecognizer(model_vosk, wf.getframerate())
        result_text = ""
        while True:
            data = wf.readframes(4000)
            if len(data) == 0: break
            if rec.AcceptWaveform(data):
                res = rec.Result()
                result_text += eval(res).get("text", "") + " "

        final_res = eval(rec.FinalResult())
        result_text += final_res.get("text", "")
        wf.close()
        os.remove(temp_path)

        return {"transcript": result_text.strip()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------- TEXT TO GESTURE -----------------
@app.post("/translate/")
async def translate(text: str = Form(...)):
    try:
        gesture_sequence = []
        words = text.strip().split()

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            for word in words:
                word_norm = word.strip().upper().replace(" ", "_")
                c.execute("""
                    SELECT g.gesture_path
                    FROM gestures g
                    JOIN signs s ON g.sign_id = s.id
                    WHERE UPPER(s.name)=?
                """, (word_norm,))
                row = c.fetchone()

                if row:
                    gesture_sequence.append(row[0])
                    continue

                # Fingerspell fallback
                i = 0
                while i < len(word_norm):
                    if i + 1 < len(word_norm) and word_norm[i:i+2] == "NG":
                        c.execute("""
                            SELECT g.gesture_path
                            FROM gestures g
                            JOIN signs s ON g.sign_id = s.id
                            WHERE UPPER(s.name)='NG'
                        """)
                        row = c.fetchone()
                        gesture_sequence.append(row[0] if row else "NG")
                        i += 2
                        continue

                    letter = word_norm[i]
                    c.execute("""
                        SELECT g.gesture_path
                        FROM gestures g
                        JOIN signs s ON g.sign_id = s.id
                        WHERE UPPER(s.name)=?
                    """, (letter,))
                    row = c.fetchone()
                    gesture_sequence.append(row[0] if row else letter)
                    i += 1

        return {"translation": gesture_sequence}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------- GRAMMAR CORRECTION -----------------
@app.post("/grammar/", response_class=PlainTextResponse)
async def grammar(text: str = Form(...)):
    try:
        if not text.strip(): 
            return ""

        # Improved prompt for FLAN-T5-LARGE
        prompt = (
            "Correct the following sentence into natural English suitable for sign language. "
            "Keep it simple and short. Do not add punctuation.\n\n"
            f"Sentence: {text}\nCorrected:"
        )       


        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            outputs = model_flan.generate(
                **inputs,
                max_length=50,
                do_sample=False,
                num_beams=5
            )
        corrected_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Remove special characters except letters, numbers, spaces, Ñ/ñ
        cleaned_text = re.sub(r"[^a-zA-Z0-9\sÑñ]", "", corrected_text)

        return cleaned_text
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------- RUN SERVER -----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
