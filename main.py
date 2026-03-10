import os
import logging
import json
import mysql.connector
import speech_recognition as sr
import httpx
import asyncio
from pydub import AudioSegment
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL") # This is needed for Webhooks

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Onboarding Questions ---
ONBOARDING_QUESTIONS = [
    "What is your full name?",
    "What is your date of birth (DD-MM-YYYY)?",
    "What is your primary occupation?",
    "Where are you located (City, State)?",
    "What is your monthly income?",
]

# --- Database ---
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=int(DB_PORT) if DB_PORT else 4000,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            ssl_disabled=False # TiDB Cloud requires SSL
        )
        return conn
    except mysql.connector.Error as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL, full_name VARCHAR(255),
            date_of_birth VARCHAR(255), occupation VARCHAR(255),
            location VARCHAR(255), monthly_income VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS user_onboarding_state (user_id BIGINT PRIMARY KEY, onboarding_step INT, answers JSON)")
    conn.commit()
    cursor.close()
    conn.close()

# --- Weather ---
async def get_weather(city: str) -> str:
    if not OPENWEATHERMAP_API_KEY: return "Weather API key not configured."
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHERMAP_API_KEY}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return f"The weather in {city} is {data['weather'][0]['main']} ({data['weather'][0]['description']})."
        except Exception as e:
            logger.error(f"Weather error: {e}")
            return f"Couldn't fetch weather for {city}."

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_onboarding_state WHERE user_id = %s", (user_id,))
    cursor.execute("INSERT INTO user_onboarding_state (user_id, onboarding_step, answers) VALUES (%s, %s, %s)", (user_id, 0, json.dumps({})))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text("Welcome to ShieldAI! Let's get you insured in 60 seconds.\n\nFirst question: What is your full name?")

async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_onboarding_state WHERE user_id = %s", (user_id,))
    user_state = cursor.fetchone()
    if user_state:
        step = user_state['onboarding_step']
        if step < len(ONBOARDING_QUESTIONS):
            await update.message.reply_text(ONBOARDING_QUESTIONS[step])
        else:
            await complete_onboarding(update, context)
    cursor.close()
    conn.close()

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_onboarding_state WHERE user_id = %s", (user_id,))
    user_state = cursor.fetchone()
    if user_state:
        step = user_state['onboarding_step']
        answers = json.loads(user_state['answers'])
        answers[ONBOARDING_QUESTIONS[step]] = update.message.text
        cursor.execute("UPDATE user_onboarding_state SET onboarding_step = %s, answers = %s WHERE user_id = %s", (step + 1, json.dumps(answers), user_id))
        conn.commit()
        await ask_next_question(update, context)
    cursor.close()
    conn.close()

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    voice = update.message.voice
    file = await voice.get_file()
    ogg_filename = f"{file.file_id}.ogg"
    wav_filename = f"{file.file_id}.wav"
    await file.download_to_drive(ogg_filename)
    try:
        audio = AudioSegment.from_ogg(ogg_filename)
        audio.export(wav_filename, format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(wav_filename) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data)
            await update.message.reply_text(f"I heard: '{text}'")
            update.message.text = text
            await handle_text_message(update, context)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Voice error. Needs ffmpeg.")
    finally:
        for f in [ogg_filename, wav_filename]:
            if os.path.exists(f): os.remove(f)

async def complete_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM user_onboarding_state WHERE user_id = %s", (user_id,))
    user_state = cursor.fetchone()
    if user_state:
        answers = json.loads(user_state['answers'])
        cursor.execute("INSERT INTO policies (user_id, full_name, date_of_birth, occupation, location, monthly_income) VALUES (%s, %s, %s, %s, %s, %s)",
                       (user_id, answers.get(ONBOARDING_QUESTIONS[0]), answers.get(ONBOARDING_QUESTIONS[1]), answers.get(ONBOARDING_QUESTIONS[2]), answers.get(ONBOARDING_QUESTIONS[3]), answers.get(ONBOARDING_QUESTIONS[4])))
        cursor.execute("DELETE FROM user_onboarding_state WHERE user_id = %s", (user_id,))
        conn.commit()
        await update.message.reply_text("Policy saved! Coverage active.")
    cursor.close()
    conn.close()

async def test_rain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    location = "Bengaluru,IN"
    await update.message.reply_text(f"Checking weather for {location}...")
    weather_report = await get_weather(location)
    await update.message.reply_text(weather_report)

async def test_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Zero-click claim simulated: ₹450 credited.")

# --- FastAPI Setup ---
app = FastAPI()
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("testrain", test_rain))
application.add_handler(CommandHandler("testclaim", test_claim))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

@app.on_event("startup")
async def on_startup():
    init_db()
    await application.initialize()
    await application.start()

@app.post("/webhook")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "ShieldAI is online"}

@app.get("/set-webhook")
async def set_webhook():
    if not RENDER_EXTERNAL_URL: return {"error": "RENDER_EXTERNAL_URL not set"}
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    success = await application.bot.set_webhook(webhook_url)
    return {"status": "webhook set", "url": webhook_url, "success": success}
