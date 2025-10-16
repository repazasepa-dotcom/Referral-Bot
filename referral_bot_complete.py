import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

users = load_data()

# -----------------------
# Helpers
# -----------------------
def get_user(user_id):
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "balance": 0,
            "referrals": [],
            "joined": datetime.utcnow().isoformat(),
            "pair_left": 0,
            "pair_right": 0,
        }
    return users[uid]

def reset_pairing_if_needed():
    for uid in users:
        users[uid]["pair_left"] = 0
        users[uid]["pair_right"] = 0
    save_data(users)
    logger.info("✅ Daily pairing reset completed.")

# -----------------------
# Command Handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    save_data(users)
    await update.message.reply_text(
        "🔥 Welcome to the Premium Member Refer-to-Earn Bot!\n\n"
        "💰 Earn rewards by inviting friends and joining our private signal group.\n"
        "Use /pay to send TXID or screenshot proof after payment."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    if update.message.photo:
        await update.message.reply_text("📸 Screenshot received! Please wait for admin confirmation.")
    elif context.args:
        txid = " ".join(context.args)
        await update.message.reply_text(f"💳 TXID received: {txid}\nPlease wait for admin confirmation.")
    else:
        await update.message.reply_text(
            "Please send either:\n"
            "• `/pay <TXID>`\n"
            "• Or attach a screenshot proof."
        )

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /confirm <user_id> <amount>")
        return
    user_id, amount = context.args[0], float(context.args[1])
    user = get_user(user_id)
    user["balance"] += amount
    save_data(users)
    await update.message.reply_text(f"✅ Confirmed payment for {user_id} (+{amount} USDT).")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    await update.message.reply_text(f"💰 Your balance: {user['balance']} USDT")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user["balance"] <= 0:
        await update.message.reply_text("⚠️ You have no balance to withdraw.")
        return
    await update.message.reply_text(
        f"💵 Withdrawal request received ({user['balance']} USDT). Please wait for admin processing."
    )

async def processwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /processwithdraw <user_id> <amount>")
        return
    user_id, amount = context.args[0], float(context.args[1])
    user = get_user(user_id)
    if user["balance"] < amount:
        await update.message.reply_text("❌ Insufficient balance.")
        return
    user["balance"] -= amount
    save_data(users)
    await update.message.reply_text(f"✅ Withdraw processed for {user_id} ({amount} USDT).")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(users)
    total_balance = sum(u["balance"] for u in users.values())
    await update.message.reply_text(
        f"📊 Total Users: {total_users}\n💰 Total Balances: {total_balance:.2f} USDT"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Commands:\n"
        "/start – Welcome message\n"
        "/pay <TXID> or send screenshot\n"
        "/confirm <user_id> <amount>\n"
        "/balance – Check balance\n"
        "/withdraw – Request withdraw\n"
        "/processwithdraw <user_id> <amount>\n"
        "/stats – System stats\n"
        "/help – Show commands"
    )

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Type /help for assistance.")

# -----------------------
# Run Bot (Render-safe)
# -----------------------
if __name__ == "__main__":
    import asyncio

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN not set!")

    app = ApplicationBuilder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(MessageHandler(filters.PHOTO, pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", processwithdraw))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(reset_pairing_if_needed, CronTrigger(hour=0, minute=0))
    scheduler.start()

    # ---- Start bot without closing the loop ----
    async def start_bot():
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("🚀 Bot running...")

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_bot())
        loop.run_forever()
    except RuntimeError:
        # fallback for pre-running loop on Render
        asyncio.ensure_future(start_bot())
        loop.run_forever()
