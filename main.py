import os
import logging
import json
import mysql.connector
import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

if not GROQ_API_KEY:
    logger.critical("GROQ_API_KEY is not set! The AI will not work.")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN is not set!")

GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """
You are ShieldAI, a friendly and professional conversational AI insurance agent. 
Your goal is to help workers get insured quickly and easily. 
You need to collect the following 5 pieces of information from the user:
1. Full Name
2. Date of Birth (DD-MM-YYYY)
3. Primary Occupation
4. Location (City, State)
5. Monthly Income

Be conversational, helpful, and empathetic. Don't just ask them like a form; engage with them.
If they ask questions about insurance, answer them clearly.
Once you have ALL 5 pieces of information, output a JSON object at the very end of your message in this EXACT format:
DATA_CAPTURED: {"full_name": "...", "dob": "...", "occupation": "...", "location": "...", "income": "..."}
"""

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, port=int(DB_PORT), user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME,
            ssl_disabled=False, connection_timeout=10
        )
        return conn
    except mysql.connector.Error as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        logger.error("Could not initialize DB - no connection.")
        return
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            user_id BIGINT PRIMARY KEY, history TEXT
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Database initialized successfully.")

async def get_weather_data(city: str):
    if not OPENWEATHERMAP_API_KEY:
        return None
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHERMAP_API_KEY}&units=metric"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Weather fetch error for {city}: {e}")
            return None

async def get_weather(city: str) -> str:
    data = await get_weather_data(city)
    if not data:
        return f"Couldn't fetch weather for {city}."
    return f"The weather in {city} is {data['weather'][0]['description']}, {data['main']['temp']}°C."

def is_rain_alert(weather_data) -> bool:
    if not weather_data:
        return False
    return 200 <= weather_data['weather'][0]['id'] <= 531

async def get_ai_response(user_id: int, user_message: str) -> str:
    conn = get_db_connection()
    if not conn:
        return "Sorry, I'm having trouble connecting to my database. Please try again in a moment."
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT history FROM chat_history WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if row and row['history']:
            for h in json.loads(row['history']):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 1000},
                timeout=30
            )
            response.raise_for_status()
            ai_text = response.json()["choices"][0]["message"]["content"]

        new_history = [m for m in messages[1:]]
        new_history.append({"role": "assistant", "content": ai_text})
        cursor.execute("REPLACE INTO chat_history (user_id, history) VALUES (%s, %s)",
                       (user_id, json.dumps(new_history)))
        conn.commit()
        return ai_text

    except Exception as e:
        import traceback
        logger.error(f"Groq API error for user {user_id}: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
        return "I'm sorry, I'm having a bit of a brain fog. Can you repeat that?"
    finally:
        cursor.close()
        conn.close()

async def morning_weather_check():
    logger.info("Running morning weather check...")
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT user_id, full_name, location FROM policies")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    for user in users:
        if not user.get('location'):
            continue
        city = user['location'].split(',')[0].strip()
        weather_data = await get_weather_data(city)
        if is_rain_alert(weather_data):
            name = user['full_name'] or "there"
            desc = weather_data['weather'][0]['description']
            msg = (f"🌧️ Good morning, {name}!\n\nHeavy {desc} is expected in {city} today. "
                   f"I've automatically activated your rain coverage. "
                   f"If you face work disruption, your payout will be processed within 2 hours. Stay safe! 🛡️")
            try:
                await application.bot.send_message(chat_id=user['user_id'], text=msg)
                logger.info(f"Rain alert sent to user {user['user_id']} for {city}")
            except Exception as e:
                logger.error(f"Failed to send alert to {user['user_id']}: {e}")

# --- Telegram Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    response = await get_ai_response(user_id, "Hello! I'm interested in insurance.")
    await update.message.reply_text(response.split("DATA_CAPTURED:")[0].strip())

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    ai_response = await get_ai_response(user_id, update.message.text)
    if "DATA_CAPTURED:" in ai_response:
        parts = ai_response.split("DATA_CAPTURED:")
        text_msg = parts[0].strip()
        try:
            data = json.loads(parts[1].strip())
            if text_msg:
                await update.message.reply_text(text_msg)
            await complete_onboarding(update, data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            await update.message.reply_text(ai_response)
    else:
        await update.message.reply_text(ai_response)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Voice messages are coming soon! For now, please type your message. 🎙️")

async def complete_onboarding(update: Update, data: dict) -> None:
    user_id = update.message.from_user.id
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("Sorry, couldn't save your policy. Please try again.")
        return
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO policies (user_id, full_name, date_of_birth, occupation, location, monthly_income) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, data.get('full_name'), data.get('dob'), data.get('occupation'), data.get('location'), data.get('income'))
        )
        cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (user_id,))
        conn.commit()
        name = data.get('full_name', 'there')
        await update.message.reply_text(
            f"🎉 Welcome to ShieldAI, {name}!\n\n✅ Your policy is now active.\n"
            f"🛡️ You're covered for weather-related work disruptions.\n"
            f"💰 Payouts happen automatically — no claims to file!\n\n"
            f"I'll message you every morning if rain is expected. Stay safe!"
        )
    except Exception as e:
        logger.error(f"Policy save error: {e}")
        await update.message.reply_text("Something went wrong saving your policy. Please try /start again.")
    finally:
        cursor.close()
        conn.close()

async def test_rain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Checking weather for Bengaluru...")
    await update.message.reply_text(await get_weather("Bengaluru,IN"))

async def test_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("✅ Zero-click claim simulated: ₹450 has been credited to your wallet!")

# --- FastAPI App ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("testrain", test_rain))
application.add_handler(CommandHandler("testclaim", test_claim))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def on_startup():
    init_db()
    await application.initialize()
    await application.start()
    scheduler.add_job(morning_weather_check, 'cron', hour=1, minute=30)
    scheduler.start()
    logger.info("ShieldAI started. Scheduler running.")

@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown()
    await application.stop()

@app.post("/webhook")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "ShieldAI is online ✅"}

@app.get("/set-webhook")
async def set_webhook():
    if not RENDER_EXTERNAL_URL:
        return {"error": "RENDER_EXTERNAL_URL not set in environment variables"}
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    success = await application.bot.set_webhook(webhook_url)
    return {"status": "webhook set", "url": webhook_url, "success": success}

# --- Web Chat API ---
class ChatMessage(BaseModel):
    session_id: str
    message: str

@app.post("/api/chat")
async def web_chat(body: ChatMessage):
    # Use a large fixed user_id offset so web users don't clash with Telegram users
    web_user_id = abs(hash(body.session_id)) % (10**12) + 9_000_000_000_000
    ai_response = await get_ai_response(web_user_id, body.message)

    policy_saved = False
    reply = ai_response

    if "DATA_CAPTURED:" in ai_response:
        parts = ai_response.split("DATA_CAPTURED:")
        reply = parts[0].strip()
        try:
            data = json.loads(parts[1].strip())
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO policies (user_id, full_name, date_of_birth, occupation, location, monthly_income) VALUES (%s, %s, %s, %s, %s, %s)",
                    (web_user_id, data.get('full_name'), data.get('dob'), data.get('occupation'), data.get('location'), data.get('income'))
                )
                cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (web_user_id,))
                conn.commit()
                cursor.close()
                conn.close()
                policy_saved = True
                name = data.get('full_name', 'there')
                reply += f"\n\n🎉 Welcome to ShieldAI, {name}! Your policy is now active. You're covered for weather-related work disruptions. 🛡️"
        except Exception as e:
            logger.error(f"Web onboarding error: {e}")

    return {"reply": reply, "policy_saved": policy_saved}

@app.post("/api/chat/reset")
async def reset_chat(body: dict):
    session_id = body.get("session_id", "")
    web_user_id = abs(hash(session_id)) % (10**12) + 9_000_000_000_000
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE user_id = %s", (web_user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    return {"status": "reset"}

# --- Admin API ---
@app.get("/api/admin/policies")
async def get_policies():
    conn = get_db_connection()
    if not conn:
        return {"error": "DB connection failed"}
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, user_id, full_name, date_of_birth, occupation, location, monthly_income, created_at FROM policies ORDER BY created_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    for row in rows:
        if row.get('created_at'):
            row['created_at'] = str(row['created_at'])
    return {"policies": rows, "total": len(rows)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)