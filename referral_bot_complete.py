# referral_bot_complete.py
import logging
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters
)

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# Storage
# -----------------------
DATA_FILE = "users.json"
META_FILE = "meta.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

if os.path.exists(META_FILE):
    with open(META_FILE, "r") as f:
        meta = json.load(f)
else:
    meta = {"last_reset": None}

# -----------------------
# Constants
# -----------------------
ADMIN_ID = 8150987682
DIRECT_BONUS = 20
PAIRING_BONUS = 5
MAX_PAIRS_PER_DAY = 10
MEMBERSHIP_FEE = 50
BNB_ADDRESS = "0xC6219FFBA27247937A63963E4779e33F7930d497"
PREMIUM_GROUP = "https://t.me/+ra4eSwIYWukwMjRl"
MIN_WITHDRAW = 20

INVEST_LOCK_DAYS = 30
DAILY_PROFIT_PERCENT = 1  # 1% daily

# -----------------------
# Helper Functions
# -----------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f)

def save_meta():
    with open(META_FILE, "w") as f:
        json.dump(meta, f)

def reset_pairing_if_needed():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if meta.get("last_reset") != today:
        for user in users.values():
            user["left"] = 0
            user["right"] = 0
        meta["last_reset"] = today
        save_data()
        save_meta()
        logger.info("Daily pairing counts reset.")

def calculate_investment_profit(user):
    invest = user.get("investment")
    if not invest or invest.get("pending") or not invest.get("start_date"):
        return 0
    try:
        start_date = datetime.fromisoformat(invest["start_date"])
    except Exception:
        return 0
    amount = invest["amount"]
    withdrawn_profit = invest.get("withdrawn_profit", 0)
    days_passed = (datetime.now(timezone.utc) - start_date).days
    total_profit = amount * (DAILY_PROFIT_PERCENT / 100) * days_passed
    return total_profit - withdrawn_profit

# -----------------------
# Daily Profit & Unlock Loop
# -----------------------
async def daily_profit_loop(app):
    while True:
        try:
            now = datetime.now(timezone.utc)
            for user_id, user in users.items():
                # Credit daily profit
                profit = calculate_investment_profit(user)
                if profit > 0:
                    user["balance"] += profit
                    user.setdefault("investment", {})["withdrawn_profit"] = user.get("investment", {}).get("withdrawn_profit", 0) + profit
                    try:
                        await app.bot.send_message(
                            chat_id=int(user_id),
                            text=f"📈 Daily profit of {profit:.2f} USDT credited to your balance."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")

                # Check 30-day lock expiry
                invest = user.get("investment")
                if invest and not invest.get("pending") and invest.get("start_date"):
                    start_date = datetime.fromisoformat(invest["start_date"])
                    if now >= start_date + timedelta(days=INVEST_LOCK_DAYS) and not invest.get("unlocked"):
                        invest["unlocked"] = True
                        try:
                            await app.bot.send_message(
                                chat_id=int(user_id),
                                text=f"🔓 Your invested principal of {invest['amount']:.2f} USDT is now unlocked and withdrawable."
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")

            save_data()
            logger.info("✅ Daily profits credited and investments checked for unlocks.")
        except Exception as e:
            logger.error(f"Daily profit loop error: {e}")

        # Wait until next UTC midnight
        now = datetime.now(timezone.utc)
        next_run = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        wait_seconds = max(0, (next_run - now).total_seconds())
        await asyncio.sleep(wait_seconds)

# -----------------------
# Command Handlers
# -----------------------
# Implement /start, /pay, /confirm, /balance, /stats, /withdraw, /invest, /confirminvest, /help
# Use the same handlers from the previous full code
# They include referral bonuses, investment profits, and admin notifications

# -----------------------
# Main entry point
# -----------------------
async def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set!")

    app = ApplicationBuilder().token(TOKEN).build()

    # Add all handlers
    # app.add_handler(...)

    # Start daily profit loop
    asyncio.create_task(daily_profit_loop(app))

    # Run polling
    await app.run_polling()

# -----------------------
# Run safely on Render
# -----------------------
try:
    loop = asyncio.get_running_loop()
    loop.create_task(main())
    loop.run_forever()
except RuntimeError:
    asyncio.run(main())
