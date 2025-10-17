import os
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ------------------ CONFIG ------------------
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
USDT_ADDRESS = os.environ.get("USDT_ADDRESS", "0xC6219FFBA27247937A63963E4779e33F7930d497")
PREMIUM_GROUP_LINK = os.environ.get("PREMIUM_GROUP_LINK", "https://t.me/+ra4eSwIYWukwMjRl")

MIN_INVESTMENT = 50
DAILY_PROFIT_PERCENT = 0.01
REFERRAL_DIRECT_BONUS = 20
PAIRING_BONUS = 5
MAX_PAIR_PER_DAY = 10
MIN_WITHDRAW = 20

# ------------------ INVESTMENTS ------------------
try:
    with open("investments.json", "r") as f:
        investments = json.load(f)
except FileNotFoundError:
    investments = {}

def save_investments():
    with open("investments.json", "w") as f:
        json.dump(investments, f, indent=4)

# ------------------ ADMIN CHECK ------------------
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            return
        return await func(update, context)
    return wrapper

# ------------------ DAILY PROFIT ------------------
async def daily_profit_job(context: ContextTypes.DEFAULT_TYPE):
    for inv in investments.values():
        if inv.get("status") == "active":
            inv.setdefault("balance", 0)
            inv["balance"] += inv["amount"] * DAILY_PROFIT_PERCENT
    save_investments()
    print("✅ Daily profit added to all active investments.")

# ------------------ USER COMMANDS ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args
    referrer = args[0] if args else None
    if referrer == user_id:
        referrer = None

    if user_id not in investments:
        investments[user_id] = {
            "amount": 0,
            "status": "none",
            "start_date": None,
            "locked_until": None,
            "balance": 0,
            "referrer": referrer,
            "pairing_bonus_today": 0,
            "last_pair_day": None
        }
        save_investments()

    await update.message.reply_text(
        f"🏁 Hello {update.effective_user.first_name}!\n"
        f"Use /invest <amount> to deposit in USDT (min {MIN_INVESTMENT} USDT).\n"
        f"Send USDT to: {USDT_ADDRESS}\n"
        f"Submit TXID with /txid <transaction_hash> after sending.\n"
        f"Check your withdrawable balance: /profit\n"
        f"Withdrawals minimum: {MIN_WITHDRAW} USDT\n\n"
        f"Your referral link:\n"
        f"t.me/{context.bot.username}?start={user_id}"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ **Available Commands:**\n\n"
        "🏁 /start - Start bot and get referral link\n"
        "💸 /invest <amount> - Make an investment (min 50 USDT)\n"
        "🔗 /txid <transaction_hash> - Submit TXID\n"
        "💹 /profit - Check withdrawable balance\n"
        "💳 /withdraw <USDT BEP20 address> - Request withdrawal (min 20 USDT)\n"
        "📊 /earnings - How you earn (profit & bonuses)\n"
        "❓ /help - Show this help message"
    )
    await update.message.reply_text(help_text)

# ------------------ INVEST, TXID, PROFIT, WITHDRAW ------------------
# Copy your previous functions here: invest(), submit_txid(), profit(), withdraw(), earnings()
# They are fully compatible with JobQueue

# ------------------ ADMIN COMMANDS ------------------
# Copy your previous admin functions here: confirm(), confirm_withdraw(), dashboard(), user_detail()
# All remain compatible

# ------------------ RUN BOT ------------------
def run_bot():
    # Force JobQueue creation by setting use_context=True (PTB v20+ handles JobQueue automatically)
    app = ApplicationBuilder().token(TOKEN).build()

    # Add all command handlers (user + admin)
    # Example:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    # Add other handlers: invest, txid, profit, withdraw, earnings, admin commands

    # ✅ Daily profit JobQueue
    app.job_queue.run_repeating(daily_profit_job, interval=86400, first=10)

    print("🤖 Bot running on Telegram...")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
