# 🛡️ Anon — Anonymous Feedback & Voice Morphing Bot

> A Telegram bot for receiving anonymous messages and feedback. Perfect for placing in channel bios or social media profiles.

## 🚀 Features

- **Personalized Feedback Links**: Generate custom links for users to send anonymous messages to your private inbox.
- **Voice Message Anonymization (Voice Morphing)**:
  - Automatically processes incoming voice notes using FFmpeg/audio filters.
  - Anonymizes the sender's voice by changing pitch, frequency, and speed parameters.
- **Text-to-Speech (TTS) Engine**:
  - Convert incoming text secrets to audio formats.
  - Multi-engine support: Integrates **Azure Cognitive Services Speech SDK** (high quality) and **edge-tts** (offline/standard fallback).
  - Customizable voices: Ostap (Male), Polina (Female), Robot, and English voice profiles.
- **Usage Tracker Limits**:
  - Implements character synthesis volume trackers to prevent API overuse.
- **Secure Database Storage**: Tracks routing links, statistics, and monthly character quotas securely.

## 🛠️ Tech Stack

- **Language**: Python 3.10+
- **Bot Engine**: `aiogram 3.x`
- **Audio Processing**: FFmpeg
- **Speech APIs**: Microsoft Azure Cognitive Services (Speech SDK) + `edge-tts`
- **Database**: SQLite (asynchronous models)
- **Deployment**: Docker, Docker Compose

## 📁 Project Structure

```
Anon/
├── src/
│   ├── services/
│   │   ├── voice_engine.py  # TTS core engine (Azure & edge-tts)
│   │   └── image_engine.py  # Graphic/media processing utilities
│   ├── handlers/            # Message routing & settings handlers
│   ├── database.py          # Routing mappings & limit queries
│   ├── config.py            # Environment configuration loader
│   ├── l10n.py              # Localization helpers
│   └── main.py              # Application entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## ⚙️ Configuration & Run

### 1. Environment Settings
Create a `.env` file in the root directory:
```env
BOT_TOKEN=your_telegram_bot_token
AZURE_SPEECH_KEY=your_azure_speech_api_key
AZURE_SPEECH_REGION=your_azure_region
```

### 2. Run with Docker Compose
```bash
docker compose up -d
```

---
*Developed by Mykhailo Chernykh.*
