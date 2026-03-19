import os
import logging
import json
import mysql.connector
import httpx
import google.generativeai as genai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Load environment variables
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Validate critical env vars on startup ---
if not GOOGLE_API_KEY:
    logger.critical("GOOGLE_API_KEY is not set! The AI will not work.")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN is not set!")

# --- Gemini Setup ---
genai.configure(api_key=GOOGLE_API_KEY)
# gemini-2.0-flash is the current stable model available on all API keys
model = genai.GenerativeModel('gemini-2.0-flash')

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

# --- Database ---
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            ssl_disabled=False,
            connection_timeout=10
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
            user_id BIGINT NOT NULL,
            full_name VARCHAR(255),
            date_of_birth VARCHAR(255),
            occupation VARCHAR(255),
            location VARCHAR(255),
            monthly_income VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            user_id BIGINT PRIMARY KEY,
            history JSON
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Database initialized successfully.")

# --- Weather ---
async def get_weather_data(city: str) -> dict | None:
    """Returns raw weather data dict, or None on failure."""
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
    desc = data['weather'][0]['description']
    temp = data['main']['temp']
    return f"The weather in {city} is {desc}, {temp}°C."

def is_rain_alert(weather_data: dict) -> bool:
    """Returns True if weather indicates heavy rain."""
    if not weather_data:
        return False
    weather_id = weather_data['weather'][0]['id']
    # OpenWeatherMap codes: 200-531 are rain/thunderstorm/drizzle
    return 200 <= weather_id <= 531

# --- AI Logic ---
async def get_ai_response(user_id: int, user_message: str) -> str:
    conn = get_db_connection()
    if not conn:
        return "Sorry, I'm having trouble connecting to my database. Please try again in a moment."

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT history FROM chat_history WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()

        history = []
        if row and row['history']:
            stored_history = json.loads(row['history'])
            for h in stored_history:
                history.append({"role": h["role"], "parts": [h["parts"][0]]})

        chat = model.start_chat(history=history)
        prompt = f"{SYSTEM_PROMPT}\n\nUser: {user_message}" if not history else user_message

        response = chat.send_message(prompt)

        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [p.text for p in content.parts]})

        cursor.execute(
            "REPLACE INTO chat_history (user_id, history) VALUES (%s, %s)",
            (user_id, json.dumps(new_history))
        )
        conn.commit()
        return response.text

    except Exception as e:
        # Log the FULL error so you can see it in Render logs
        import traceback
        logger.error(f"Gemini API error for user {user_id}: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
        return "I'm sorry, I'm having a bit of a brain fog. Can you repeat that?"

    finally:
        cursor.close()
        conn.close()

# --- Proactive Weather Scheduler ---
async def morning_weather_check():
    """Runs daily. Checks weather for all insured users and sends rain alerts."""
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
            message = (
                f"🌧️ Good morning, {name}!\n\n"
                f"Heavy {desc} is expected in {city} today. "
                f"I've automatically activated your rain coverage. "
                f"If you face work disruption, your payout will be processed within 2 hours. Stay safe! 🛡️"
            )
            try:
                await application.bot.send_message(chat_id=user['user_id'], text=message)
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
    user_text = update.message.text
    ai_response = await get_ai_response(user_id, user_text)

    if "DATA_CAPTURED:" in ai_response:
        parts = ai_response.split("DATA_CAPTURED:")
        text_msg = parts[0].strip()
        data_json = parts[1].strip()
        try:
            data = json.loads(data_json)
            if text_msg:
                await update.message.reply_text(text_msg)
            await complete_onboarding(update, data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e} | Raw: {data_json}")
            await update.message.reply_text(ai_response)
    else:
        await update.message.reply_text(ai_response)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Voice messages are coming soon! For now, please type your message. 🎙️"
    )

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
            f"🎉 Welcome to ShieldAI, {name}!\n\n"
            f"✅ Your policy is now active.\n"
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
    location = "Bengaluru,IN"
    await update.message.reply_text(f"Checking weather for {location}...")
    weather_report = await get_weather(location)
    await update.message.reply_text(weather_report)

async def test_claim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("✅ Zero-click claim simulated: ₹450 has been credited to your wallet!")

# --- FastAPI Setup ---
app = FastAPI()
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
    # Schedule morning weather check at 7:00 AM IST (01:30 UTC)
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
