from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from vosk import Model, KaldiRecognizer
import wave, os, sqlite3, uuid, re
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch
from spellchecker import SpellChecker

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

# Load grammar correction model (Grammarly CoEdit)
MODEL_NAME = "grammarly/coedit-large"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model_grammar = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

# Init spell checker
spell = SpellChecker()

def spell_correct(text: str) -> str:
    corrected_words = []
    for word in text.split():
        if not word.strip():
            continue
        corrected = spell.correction(word)
        corrected_words.append(corrected if corrected else word)
    return " ".join(corrected_words)

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
            if len(data) == 0:
                break
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
        translation_sequence = []
        words = text.strip().split()

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            i = 0
            while i < len(words):
                matched = False
                for span in range(3, 0, -1):
                    if i + span > len(words):
                        continue
                    # Clean words only for lookup
                    phrase = "_".join([re.sub(r"[^A-ZÑ]", "", w.upper()) for w in words[i:i+span]])
                    c.execute("""
                        SELECT g.gesture_path
                        FROM gestures g
                        JOIN signs s ON g.sign_id = s.id
                        WHERE UPPER(s.name)=?
                    """, (phrase,))
                    row = c.fetchone()
                    if row:
                        gesture_name = os.path.splitext(os.path.basename(row[0]))[0].upper()
                        translation_sequence.append({"word": " ".join(words[i:i+span]), "gestures":[gesture_name]})
                        i += span
                        matched = True
                        break
                if not matched:
                    # Fingerspell each letter for unknown words
                    word = words[i]
                    finger_letters = []
                    for ch in word.upper():
                        if not ch.isalpha() and ch not in ["Ñ"]:  # keep letters only
                            continue
                        c.execute("""
                            SELECT g.gesture_path
                            FROM gestures g
                            JOIN signs s ON g.sign_id = s.id
                            WHERE UPPER(s.name)=?
                        """, (ch,))
                        row = c.fetchone()
                        letter_name = os.path.splitext(os.path.basename(row[0]))[0].upper() if row else ch
                        finger_letters.append(letter_name)
                    translation_sequence.append({"word": word, "gestures": finger_letters})
                    i += 1

        return {"translation": translation_sequence}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ----------------- GRAMMAR + SPELL CORRECTION -----------------
@app.post("/grammar/", response_class=PlainTextResponse)
async def grammar(text: str = Form(...)):
    try:
        if not text.strip():
            return ""

        # Step 1: Spell correction
        text = spell_correct(text)

        # Step 2: Grammar correction (Grammarly CoEdit)
        inputs = tokenizer(text, return_tensors="pt").to("cpu")
        with torch.no_grad():
            outputs = model_grammar.generate(
                **inputs,
                max_length=128,
                do_sample=False,
                num_beams=5
            )
        corrected_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Step 3: Light cleanup (keep punctuation and ñ/Ñ)
        cleaned_text = re.sub(r"[^a-zA-Z0-9\s,.?!'Ññ]", "", corrected_text)

        return cleaned_text.strip()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ----------------- RUN SERVER -----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="key.pem",
        ssl_certfile="cert.pem"
    )
