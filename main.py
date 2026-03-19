import os
import logging
import json
import mysql.connector
import speech_recognition as sr
import httpx
import google.generativeai as genai
from pydub import AudioSegment
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pydantic import BaseModel

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
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Gemini Setup ---
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

SYSTEM_PROMPT = """
You are ShieldAI, a highly specialized AI Insurance Agent for gig workers (delivery partners, drivers, etc.). 
Your specialty is 'Parametric Rain Protection'. 

HOW IT WORKS:
- If it rains heavily in the worker's location, they get an instant payout. No forms, no proof of loss. 
- We track the weather via satellites and IoT sensors.
- Coverage costs ₹99/week. Payout is ₹450 per disruption.

YOUR TASKS:
1. ONBOARDING: Naturally collect: Full Name, DOB, Occupation, Location, and Monthly Income.
2. EDUCATION: Explain why gig workers need this. (Income loss during rain, safety, etc.)
3. CLAIMS: If a user mentions it's raining or wants money, you MUST check the weather first (the system will provide it to you). 
4. PREMIUMS: Tell them their premium is ₹99/week based on their profile.

STYLE: Professional, empathetic, and Indian-gig-worker-friendly. Use a mix of English and 'Hinglish' if appropriate.

IMPORTANT:
- Once you have the 5 onboarding details, output: DATA_CAPTURED: {"full_name": "...", "dob": "...", "occupation": "...", "location": "...", "income": "..."}
- If a user wants to claim, and weather data shows rain, output: CLAIM_TRIGGERED: {"amount": 450, "reason": "Heavy Rain Detected"}
"""

# --- Database ---
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=int(DB_PORT) if DB_PORT else 4000,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            ssl_disabled=False
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
            user_id VARCHAR(255) NOT NULL, full_name VARCHAR(255),
            date_of_birth VARCHAR(255), occupation VARCHAR(255),
            location VARCHAR(255), monthly_income VARCHAR(255),
            status VARCHAR(50) DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS chat_history (user_id VARCHAR(255) PRIMARY KEY, history JSON)")
    conn.commit()
    cursor.close()
    conn.close()

# --- Weather ---
async def get_weather_data(city: str) -> str:
    if not OPENWEATHERMAP_API_KEY: return "Weather system unavailable."
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHERMAP_API_KEY}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            data = response.json()
            main = data['weather'][0]['main']
            desc = data['weather'][0]['description']
            return f"Current Weather in {city}: {main} ({desc})"
        except:
            return "Unable to verify weather at this moment."

# --- AI Logic ---
async def get_ai_response(user_id: str, user_message: str) -> str:
    conn = get_db_connection()
    if not conn: return "Database offline."
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT history FROM chat_history WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    
    # Get Location if they are already onboarded
    cursor.execute("SELECT location FROM policies WHERE user_id = %s", (user_id,))
    policy = cursor.fetchone()
    location_context = ""
    if policy:
        weather = await get_weather_data(policy['location'])
        location_context = f"\n[SYSTEM CONTEXT: User Location is {policy['location']}. {weather}]"

    history = []
    if row:
        stored_history = json.loads(row['history'])
        for h in stored_history:
            history.append({"role": h["role"], "parts": [h["parts"][0]]})
    
    chat = model.start_chat(history=history)
    # The brain now gets the weather context automatically
    prompt = f"{SYSTEM_PROMPT}{location_context}\n\nUser: {user_message}"
    
    try:
        response = chat.send_message(prompt)
        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [p.text for p in content.parts]})
        cursor.execute("REPLACE INTO chat_history (user_id, history) VALUES (%s, %s)", (user_id, json.dumps(new_history)))
        conn.commit()
        return response.text
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "I'm experiencing a bit of a delay. Could you say that again?"
    finally:
        cursor.close()
        conn.close()

# --- FastAPI & UI ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

class ChatRequest(BaseModel):
    userId: str
    message: str

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    ai_response = await get_ai_response(req.userId, req.message)
    
    # Process Actions
    if "DATA_CAPTURED:" in ai_response:
        data = json.loads(ai_response.split("DATA_CAPTURED:")[1].strip())
        await save_policy(req.userId, data)
    
    if "CLAIM_TRIGGERED:" in ai_response:
        # In a real app, this would call Razorpay
        pass

    clean_response = ai_response.split("DATA_CAPTURED:")[0].split("CLAIM_TRIGGERED:")[0].strip()
    return {"reply": clean_response}

async def save_policy(user_id, data):
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO policies (user_id, full_name, date_of_birth, occupation, location, monthly_income) VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, data.get('full_name'), data.get('dob'), data.get('occupation'), data.get('location'), data.get('income'))
    )
    conn.commit()
    cursor.close()
    conn.close()

# --- Telegram ---
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

async def handle_tg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    ai_response = await get_ai_response(user_id, update.message.text)
    
    if "DATA_CAPTURED:" in ai_response:
        data = json.loads(ai_response.split("DATA_CAPTURED:")[1].strip())
        await save_policy(user_id, data)
    
    clean_msg = ai_response.split("DATA_CAPTURED:")[0].split("CLAIM_TRIGGERED:")[0].strip()
    await update.message.reply_text(clean_msg)

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tg))
application.add_handler(CommandHandler("start", handle_tg)) # Treat start as a message

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

@app.get("/set-webhook")
async def set_webhook():
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    await application.bot.set_webhook(webhook_url)
    return {"status": "webhook set"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
