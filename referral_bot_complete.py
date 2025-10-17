# referral_bot_render.py
import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# -----------------------
# Storage files
# -----------------------
DATA_FILE = "/mnt/data/users.json"
META_FILE = "/mnt/data/meta.json"

# -----------------------
# Load storage
# -----------------------
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
DAILY_PROFIT_PERCENT = 1
INVEST_LOCK_DAYS = 30

# -----------------------
# Helper functions
# -----------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f)

def save_meta():
    with open(META_FILE, "w") as f:
        json.dump(meta, f)

def reset_pairing_if_needed():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if meta.get("last_reset") != today:
        for user in users.values():
            user["left"] = 0
            user["right"] = 0
        meta["last_reset"] = today
        save_data()
        save_meta()
        logger.info("Daily pairing counts reset.")

def add_daily_profit():
    for user in users.values():
        if user.get("investment_confirmed"):
            profit = round(user["investment_balance"] * DAILY_PROFIT_PERCENT / 100, 2)
            user["investment_balance"] += profit
            user["profit_earned"] = user.get("profit_earned", 0) + profit
    save_data()
    logger.info("Daily profit added to investments.")

# -----------------------
# /start command
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)

    if user_id not in users:
        users[user_id] = {
            "referrer": None,
            "balance": 0,
            "earned_from_referrals": 0,
            "left": 0,
            "right": 0,
            "referrals": [],
            "paid": False,
            "txid": None,
            "investment_balance": 0,
            "investment_txid": None,
            "investment_confirmed": False,
            "investment_date": None,
            "profit_earned": 0
        }

        # Referral handling
        if context.args:
            ref_id = context.args[0]
            if ref_id in users and ref_id != user_id:
                users[user_id]["referrer"] = ref_id
                users[ref_id].setdefault("referrals", []).append(user_id)

    save_data()

    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"
    benefits_text = (
        "🔥 Premium Membership Benefits 🔥\n\n"
        "🚀 Get Coin names before pump\n"
        "🚀 Guidance on buy & sell targets\n"
        "🚀 Receive 2-5 daily signals\n"
        "🚀 Auto trading by bot\n"
        "🚀 1-3 special signals daily in premium channel\n\n"
    )

    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BNB Smart Chain BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"Share your referral link to earn bonuses after your friends pay:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# /pay command
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ Already confirmed as paid")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /pay <TXID>")
        return

    txid = context.args[0]
    user["txid"] = txid
    save_data()

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💳 New payment TXID submitted!\nUser ID: {user_id}\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")

    await update.message.reply_text("✅ TXID submitted. Admin will verify soon.")

# -----------------------
# /invest command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /invest <TXID>")
        return

    txid = context.args[0]
    user["investment_txid"] = txid
    save_data()

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New investment TXID submitted!\nUser ID: {user_id}\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")

    await update.message.reply_text("✅ Investment TXID submitted. Admin will confirm.")

# -----------------------
# /confirminvest command
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /confirminvest <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or not user.get("investment_txid"):
        await update.message.reply_text("❌ No investment TXID submitted")
        return

    user["investment_confirmed"] = True
    user["investment_date"] = datetime.utcnow().isoformat()
    save_data()

    await update.message.reply_text(f"✅ Investment confirmed for {target_user_id}")

# -----------------------
# /myinvestment command
# -----------------------
async def myinvestment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first")
        return
    balance = user.get("investment_balance", 0)
    profit = user.get("profit_earned", 0)
    await update.message.reply_text(
        f"💰 Investment Balance: {balance} USDT\n"
        f"📈 Total Profit: {profit} USDT\n"
        f"🔒 Locked for {INVEST_LOCK_DAYS} days after deposit"
    )

# -----------------------
# /balance command
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first")
        return
    bal = user.get("balance", 0)
    earned = user.get("earned_from_referrals", 0)
    await update.message.reply_text(f"💰 Balance: {bal} USDT\n💎 Earned from referrals: {earned} USDT")

# -----------------------
# /help command
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    help_text = (
        "📌 Commands:\n"
        "/start - Register & get referral link\n"
        "/balance - Check balance\n"
        "/myinvestment - Investment summary\n"
        "/withdraw <BEP20> - Request withdrawal\n"
        "/pay <TXID> - Membership payment\n"
        "/invest <TXID> - Submit investment\n"
        "/help - This menu"
    )
    if is_admin:
        help_text += (
            "\n--- Admin ---\n"
            "/confirm <user_id> - Confirm membership\n"
            "/confirminvest <user_id> - Confirm investment\n"
            "/processwithdraw <user_id> - Process withdrawal"
        )
    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help")

# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirminvest", confirm_invest))
    app.add_handler(CommandHandler("myinvestment", myinvestment))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(reset_pairing_if_needed, 'cron', hour=0, minute=0)
    scheduler.add_job(add_daily_profit, 'cron', hour=0, minute=5)
    scheduler.start()

    # Run bot
    app.run_polling()
