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
if not GOOGLE_API_KEY:
    logger.error("CRITICAL: GOOGLE_API_KEY is not set in environment variables!")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

SYSTEM_PROMPT = """
You are ShieldAI, a friendly and professional conversational AI insurance agent for gig workers. 
Your goal is to help workers get 'Parametric Rain Protection'.
Premium is ₹99/week. Payout is ₹450 per disruption.

YOUR TASKS:
1. Naturally collect: Full Name, Date of Birth (DD-MM-YYYY), Primary Occupation, Location (City, State), and Monthly Income.
2. Explain the benefits of rain insurance for workers.
3. Once you have ALL 5 onboarding details, output exactly: DATA_CAPTURED: {"full_name": "...", "dob": "...", "occupation": "...", "location": "...", "income": "..."}
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
    except Exception as e:
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

# --- AI Logic ---
async def get_ai_response(user_id: str, user_message: str) -> str:
    conn = get_db_connection()
    if not conn: return "Database connection error. Please try again later."
    
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT history FROM chat_history WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        
        # Format history for Gemini
        history = []
        if row and row['history']:
            try:
                stored_history = json.loads(row['history'])
                for h in stored_history:
                    # Validate format
                    if "role" in h and "parts" in h:
                        history.append({"role": h["role"], "parts": [str(h["parts"][0])]})
            except Exception as e:
                logger.error(f"Error parsing history: {e}")

        chat = model.start_chat(history=history)
        
        # If it's a new chat, prefix with system prompt
        full_message = f"{SYSTEM_PROMPT}\n\nUser: {user_message}" if not history else user_message
        
        response = chat.send_message(full_message)
        
        # Save new history
        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [p.text for p in content.parts]})
            
        cursor.execute("REPLACE INTO chat_history (user_id, history) VALUES (%s, %s)", (user_id, json.dumps(new_history)))
        conn.commit()
        return response.text
    except Exception as e:
        logger.error(f"AI ERROR for user {user_id}: {e}")
        return "I'm having a bit of trouble thinking right now. Please try again in a moment."
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
    if req.message == "/start":
        await reset_user(req.userId)
        msg = "Hello! I want to learn about ShieldAI."
    else:
        msg = req.message

    ai_response = await get_ai_response(req.userId, msg)
    
    if "DATA_CAPTURED:" in ai_response:
        try:
            data = json.loads(ai_response.split("DATA_CAPTURED:")[1].strip())
            await save_policy(req.userId, data)
        except: pass
    
    clean_response = ai_response.split("DATA_CAPTURED:")[0].strip()
    return {"reply": clean_response}

async def reset_user(user_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()

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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    await reset_user(user_id)
    response = await get_ai_response(user_id, "Hello! I want to get insured.")
    await update.message.reply_text(response.split("DATA_CAPTURED:")[0].strip())

async def handle_tg_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    ai_response = await get_ai_response(user_id, update.message.text)
    
    if "DATA_CAPTURED:" in ai_response:
        try:
            data = json.loads(ai_response.split("DATA_CAPTURED:")[1].strip())
            await save_policy(user_id, data)
        except: pass
    
    clean_msg = ai_response.split("DATA_CAPTURED:")[0].strip()
    await update.message.reply_text(clean_msg)

application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tg_text))

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
    return {"status": "webhook set", "url": webhook_url}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
