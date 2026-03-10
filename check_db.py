import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv('C:/Users/psych/ShieldAI-bot/.env')

try:
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    cursor = conn.cursor()
    cursor.execute('SHOW DATABASES LIKE "shieldai_db"')
    db = cursor.fetchone()
    if db:
        print(f"Database {db[0]} exists.")
    else:
        print("Database shieldai_db does not exist.")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
