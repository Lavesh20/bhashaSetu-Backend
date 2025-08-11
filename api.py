


from flask import Flask, request, jsonify, send_from_directory
import fitz  # PyMuPDF
import google.generativeai as genai
import os
import re
import asyncio
import edge_tts
from werkzeug.utils import secure_filename
from flask_cors import CORS



# CONFIG
app = Flask(__name__)
CORS(app, origins=["https://bhashasetu-kappa.vercel.app"])
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in environment")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Language-to-voice map (Edge TTS)
LANGUAGE_VOICE_MAP = {
    "Hindi": "hi-IN-SwaraNeural",
    "Tamil": "ta-IN-PallaviNeural",
    "Marathi": "mr-IN-AarohiNeural",
    "Gujarati": "gu-IN-DhwaniNeural",
    "Punjabi": "pa-IN-GaganNeural",
    "Bengali": "bn-IN-TanishaaNeural",
    "Telugu": "te-IN-ShrutiNeural",
    "Kannada": "kn-IN-SapnaNeural",
    "Malayalam": "ml-IN-SobhanaNeural",
    "English": "en-IN-NeerjaNeural",  # Indian English
}

# UTILS
def extract_text_from_pdf(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()

# def extract_text_from_image(image_path):
#     try:
#         import pytesseract
#         img = Image.open(image_path)
#         text = pytesseract.image_to_string(img)
#         return text.strip()
#     except ImportError:
#         # Fallback: use basic OCR or return empty
#         return "OCR not available. Please install pytesseract."
#     except Exception as e:
#         return f"Error extracting text from image: {str(e)}"

def extract_text_from_file(file_path, file_type):
    if file_type == 'application/pdf':
        return extract_text_from_pdf(file_path)
    # elif file_type.startswith('image/'):
    #     return extract_text_from_image(file_path)
    else:
        return ""

def clean_output(text):
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def save_to_file(text, lang):
    filename = f"output_translated_{lang.lower()}.txt"
    path = os.path.join(UPLOAD_FOLDER, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path

async def generate_audio(text, lang):
    lang = lang.strip().title()
    print(f"[DEBUG] generate_audio called with lang = {repr(lang)}")
    print(f"[DEBUG] Available voice keys: {list(LANGUAGE_VOICE_MAP.keys())}")
    
    voice = LANGUAGE_VOICE_MAP.get(lang)
    if not voice:
        raise ValueError(f"Edge TTS voice not found for language: '{lang}'. Available: {list(LANGUAGE_VOICE_MAP.keys())}")

    # Limit text length for TTS (edge-tts has limits)
    if len(text) > 5000:
        text = text[:5000] + "..."
        print(f"[DEBUG] Text truncated to 5000 characters for TTS")

    filename = f"output_audio_{lang.lower()}.mp3"
    path = os.path.join(UPLOAD_FOLDER, filename)
    
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(path)
        print(f"[DEBUG] Audio file saved successfully: {path}")
        return path
    except Exception as e:
        print(f"[ERROR] Failed to generate audio: {e}")
        raise


# ROUTES

@app.route("/" , methods = ["GET"])
def index():
    return jsonify({"message": "Welcome to the Translation API"})

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"})

@app.route("/uploads/<filename>")
def serve_audio(filename):
    """Serve audio files from the uploads directory"""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/translate", methods=["POST"])
def translate():
    if "file" not in request.files or "target_lang" not in request.form:
        return jsonify({"error": "Missing file or target_lang"}), 400

    file = request.files["file"]
    target_lang = request.form["target_lang"].strip()

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        # Extract text based on file type
        extracted_text = extract_text_from_file(file_path, file.content_type)
        if not extracted_text:
            return jsonify({"error": "No text found in the uploaded file"}), 400

        # Translate using Gemini
        prompt = f"Translate the following English text into {target_lang}:\n\n{extracted_text}"
        response = model.generate_content(prompt)
        translated = clean_output(response.text)

        # Save translated text
        output_path = save_to_file(translated, target_lang)

        # Generate audio using Edge TTS (async)
        try:
            audio_path = asyncio.run(generate_audio(translated, target_lang))
            audio_filename = os.path.basename(audio_path)
        except Exception as audio_error:
            print(f"[ERROR] Audio generation failed: {audio_error}")
            # Continue without audio if TTS fails
            audio_filename = None

        response_data = {
            "translation": translated,
            "output_file": os.path.basename(output_path)
        }
        
        if audio_filename:
            response_data["audio_file"] = audio_filename

        return jsonify(response_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# MAIN
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
