<div align="center">

<img src="https://img.shields.io/badge/ShieldAI-Mutual%20Protection-6c63ff?style=for-the-badge&logo=shield&logoColor=white" alt="ShieldAI"/>

# 🛡️ ShieldAI — Zero-Click Coverage

### *Protection that finds you. Not the other way around.*

[![Live Demo](https://img.shields.io/badge/🌐%20Live%20Demo-shield--ai--bot.vercel.app-6c63ff?style=for-the-badge)](https://shield-ai-bot.vercel.app)
[![Telegram Bot](https://img.shields.io/badge/🤖%20Telegram-@DevTSAIbot-2CA5E0?style=for-the-badge&logo=telegram)](https://t.me/DevTSAIbot)
[![Backend](https://img.shields.io/badge/⚡%20Backend-Render-46E3B7?style=for-the-badge)](https://shieldai-bot.onrender.com)

<br/>

> **450 million informal workers in India lose their income when it rains.**
> ShieldAI protects them through a simple chat — no forms, no agents, no friction.

<br/>

![ShieldAI Demo](https://img.shields.io/badge/Status-Live%20%26%20Deployed-00d4aa?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=flat-square)
![TiDB](https://img.shields.io/badge/TiDB-Cloud-CC0000?style=flat-square)
![Vercel](https://img.shields.io/badge/Vercel-Deployed-000000?style=flat-square&logo=vercel)

</div>

---

## 🎯 The Problem

Every time it rains in India:
- 🚫 Street vendors **pack up and lose a day's income**
- 🚫 Construction workers **can't work**
- 🚫 Auto drivers **sit idle**

Traditional financial protection has **never reached** these 450 million people — too much paperwork, too many middlemen, too complicated.

## ✨ The Solution

ShieldAI makes protection **invisible** — it works in the background so workers never have to think about it.

```
Worker chats on Telegram or Web  →  AI collects details conversationally
         ↓
Coverage activates instantly  →  Stored in TiDB Cloud
         ↓
Scheduler checks weather every morning at 7 AM IST
         ↓
Rain detected?  →  Auto-alert sent + Zero-click payout triggered
```

---

## 🚀 Live Demo

| Platform | Link |
|----------|------|
| 🌐 Website | [shield-ai-bot.vercel.app](https://shield-ai-bot.vercel.app) |
| 🤖 Telegram Bot | [@DevTSAIbot](https://t.me/DevTSAIbot) |
| ⚡ API Backend | [shieldai-bot.onrender.com](https://shieldai-bot.onrender.com) |

### Try it yourself:
1. Visit the website or open Telegram
2. Type `/start`
3. Chat naturally — give your name, DOB, occupation, location, income
4. Coverage activates instantly 🛡️
5. Type `/testrain` to see live weather monitoring
6. Type `/testclaim` to simulate a zero-click payout

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    USER INTERFACES                   │
│         🌐 Vercel Website  +  📱 Telegram Bot        │
└──────────────────┬──────────────────────────────────┘
                   │ webhook / API calls
┌──────────────────▼──────────────────────────────────┐
│              FASTAPI BACKEND (Render)                │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────┐    │
│  │   Groq AI        │    │   APScheduler         │    │
│  │  Llama 3.3 70B  │    │  Daily 7AM IST check  │    │
│  └─────────────────┘    └──────────────────────┘    │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────┐    │
│  │  OpenWeatherMap  │    │    TiDB Cloud         │    │
│  │  Rain Detection  │    │  policies + history   │    │
│  └─────────────────┘    └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
                   │ ping every 5 mins
         ⏰ cron-job.org (keeps server alive)
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| 🤖 AI Brain | Groq API — Llama 3.3 70B Versatile |
| ⚙️ Backend | Python + FastAPI |
| 📱 Bot Interface | python-telegram-bot (Webhook mode) |
| 🗄️ Database | TiDB Cloud (MySQL-compatible, serverless) |
| 🌤️ Weather | OpenWeatherMap API |
| ⏰ Scheduler | APScheduler (daily 7 AM IST) |
| 🌐 Frontend | Vanilla HTML/CSS/JS (single file!) |
| 🚀 Hosting | Render (backend) + Vercel (frontend) |
| 💓 Uptime | cron-job.org (5-min pings) |

---

## 📁 Project Structure

```
ShieldAI-bot/
├── main.py          # FastAPI backend — bot, AI, API, scheduler
├── index.html       # Entire frontend — landing page + chat + admin
├── requirements.txt # Python dependencies
├── Procfile         # Render deployment config
├── vercel.json      # Vercel static deployment config
├── .env             # Environment variables (not in repo)
└── .gitignore       # Keeps secrets safe
```

---

## ⚡ Key Features

- **💬 Conversational Onboarding** — AI collects all details naturally, one question at a time
- **🌧️ Proactive Weather Alerts** — Daily 7 AM IST check for every worker's city
- **⚡ Zero-Click Payouts** — Triggered automatically when rain is detected
- **📱 Dual Interface** — Works on both Telegram and the web
- **🗄️ Unified Database** — Telegram and web users in the same TiDB Cloud DB
- **🔄 Persistent Chat History** — AI remembers context across messages
- **📊 Admin Dashboard** — Real-time coverage management
- **🤝 Community-First** — Workers help workers through a shared protection pool

---

## 🔧 Environment Variables

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
DB_HOST=your_tidb_host
DB_PORT=4000
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=shieldai_db
OPENWEATHERMAP_API_KEY=your_openweather_key
RENDER_EXTERNAL_URL=https://your-app.onrender.com
```

---

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Begin onboarding — get covered through conversation |
| `/testrain` | Check live weather (demos Bengaluru) |
| `/testclaim` | Simulate a zero-click payout |

---

## 🗺️ Roadmap

- [x] Conversational AI onboarding
- [x] Telegram bot integration
- [x] Web chat interface
- [x] Admin dashboard
- [x] Live weather monitoring
- [x] Proactive rain alerts
- [x] Zero-click payout simulation
- [ ] Real UPI payouts via Razorpay
- [ ] WhatsApp support via Twilio
- [ ] Voice onboarding in Hindi & Tamil
- [ ] Admin authentication & login
- [ ] Multi-language support
- [ ] Community pooling model
- [ ] Heatwave & flood coverage

---

## 👥 Team

| Name | Role |
|------|------|
| Syed Gaffar Mohammed | Backend, AI, Deployment |
| Janavi Paranivel | Research, Presentation |

---

## 🏆 Built For

**DevTrails Hackathon** — Built with ❤️ to protect India's invisible workforce.

---

<div align="center">

*"Financial protection has always been designed for people who already have everything.*
*ShieldAI is designed for everyone else."*

<br/>

[![Made with Python](https://img.shields.io/badge/Made%20with-Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Powered by Groq](https://img.shields.io/badge/Powered%20by-Groq%20AI-F55036?style=flat-square)](https://groq.com)
[![Deployed on Vercel](https://img.shields.io/badge/Deployed%20on-Vercel-000000?style=flat-square&logo=vercel)](https://vercel.com)

</div>
