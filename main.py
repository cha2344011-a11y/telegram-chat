import asyncio
import logging
import os
import sys
import threading
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# Flask app for health check (run.claw.cloud requires an open port)
app = Flask(__name__)
bot_status = "stopped"
personality_name = "Unknown"

@app.route("/")
def index():
    return jsonify({
        "status": "running",
        "message": f"AI Telegram Userbot ({personality_name}) is active 🤖",
        "bot_status": bot_status
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


async def main():
    global bot_status, personality_name
    
    from ai_engine import AIEngine
    from userbot import HumanBot
    from personalities import get_personality
    
    # ========== CONFIG ==========
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        logger.error("❌ GEMINI_API_KEY not set! Please add it to .env")
        sys.exit(1)
    
    ai_engine = AIEngine(api_key=gemini_key)
    
    # Parse target groups
    groups_raw = os.environ.get("TARGET_GROUPS", "")
    target_groups = []
    for g in groups_raw.split(","):
        g = g.strip()
        if g:
            try:
                target_groups.append(int(g))
            except ValueError:
                target_groups.append(g)  # username like @mygroup
    
    if not target_groups:
        logger.warning("⚠️ No TARGET_GROUPS set! Bot will not listen to any groups.")
    
    config = {
        "MIN_REPLY_DELAY": os.environ.get("MIN_REPLY_DELAY", "8"),
        "MAX_REPLY_DELAY": os.environ.get("MAX_REPLY_DELAY", "35"),
        "REPLY_CHANCE": os.environ.get("REPLY_CHANCE", "0.4"),
        "TYPING_SPEED": os.environ.get("TYPING_SPEED", "12"),
    }
    
    # ========== BOT CREDENTIALS ==========
    bots = []
    
    for i in range(1, 3):  # Account 1 and 2
        api_id = os.environ.get(f"API_ID_{i}")
        api_hash = os.environ.get(f"API_HASH_{i}")
        phone = os.environ.get(f"PHONE_{i}")
        session_string = os.environ.get(f"SESSION_STRING_{i}", "")
        bot_key = os.environ.get(f"PERSONALITY_{i}", f"bot{i}").strip().lower()
        
        if not (api_id and api_hash and phone):
            logger.warning(f"⚠️ Account {i} incomplete credentials. Check API_ID_{i}, API_HASH_{i}, PHONE_{i} in .env")
            continue
            
        personality_info = get_personality(bot_key)
        
        bot = HumanBot(
            bot_key=bot_key,
            api_id=int(api_id),
            api_hash=api_hash,
            phone=phone,
            session_string=session_string,
            ai_engine=ai_engine,
            target_groups=target_groups,
            config=config,
        )
        bots.append((bot, personality_info["name"]))

    if not bots:
        logger.error("❌ No bots configured! Please check credentials in .env")
        sys.exit(1)
        
    # ========== START BOTS ==========
    bot_status = "starting"
    active_clients = []
    names = []
    
    for bot, p_name in bots:
        logger.info(f"🚀 Starting userbot as {p_name} ({bot.bot_key})...")
        try:
            await bot.start()
            active_clients.append(bot.client)
            names.append(p_name)
        except Exception as e:
            logger.error(f"Failed to start bot {p_name}: {e}")

    if not active_clients:
        logger.error("❌ Failed to start any bots. Exiting.")
        sys.exit(1)

    bot_status = "running"
    personality_name = ", ".join(names)
    logger.info(f"✅ Active bots ({personality_name}) started! Running indefinitely...")
    
    # Run clients
    await asyncio.gather(*(client.run_until_disconnected() for client in active_clients))


if __name__ == "__main__":
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("🌐 Flask health server started")
    
    # Run the async bot
    asyncio.run(main())
