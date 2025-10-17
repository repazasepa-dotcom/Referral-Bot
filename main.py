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

# ------------------ LOAD INVESTMENTS ------------------
try:
    with open("investments.json", "r") as f:
        investments = json.load(f)
except FileNotFoundError:
    investments = {}

# ------------------ ADMIN CHECK ------------------
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            return
        return await func(update, context)
    return wrapper

def save_investments():
    with open("investments.json", "w") as f:
        json.dump(investments, f, indent=4)

# ------------------ USER COMMANDS ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args
    referrer = None
    if args:
        referrer = args[0]
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
        f"🏁 Hello {update.effective_user.first_name}! 💰\n"
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

async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    earnings_text = (
        "💰 **How You Earn** 💰\n\n"
        "1️⃣ Daily Profit:\n"
        f"• You earn {DAILY_PROFIT_PERCENT*100}% of your investment every 24 hours.\n"
        "• Accumulated profit added to your withdrawable balance.\n\n"
        "2️⃣ Referral Bonus:\n"
        f"• Direct referral: {REFERRAL_DIRECT_BONUS} USDT per referred user 🎁\n"
        f"• Pairing bonus: {PAIRING_BONUS} USDT max {MAX_PAIR_PER_DAY} pairs/day 💎\n\n"
        "3️⃣ Withdrawals:\n"
        f"• Minimum withdrawal: {MIN_WITHDRAW} USDT 💳\n"
        "• Withdrawals confirmed by admin before sending."
    )
    await update.message.reply_text(earnings_text)

async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    try:
        amount = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(f"Usage: /invest <amount>\nMinimum: {MIN_INVESTMENT} USDT")
        return
    if amount < MIN_INVESTMENT:
        await update.message.reply_text(f"Minimum investment is {MIN_INVESTMENT} USDT")
        return

    benefits_text = (
        "🔥 **Benefits you will get after investment** 🔥\n\n"
        "• 🚀 Coin names before pump\n"
        "• 🚀 Guidance on buy/sell targets\n"
        "• 🚀 2-5 daily signals\n"
        "• 🚀 Auto trading by bot\n"
        "• 🚀 Special 1-3 daily premium signals (coins expected to pump within 24h)\n"
        "• 🚀 Trade on Binance\n"
    )
    await update.message.reply_text(benefits_text)

    inv = investments[user_id]
    if inv["status"] not in ["none", "withdrawn"]:
        await update.message.reply_text("❌ You already have a pending or active investment.")
        return

    inv["amount"] = amount
    inv["status"] = "pending"
    save_investments()

    await update.message.reply_text(
        f"✅ Investment request for {amount} USDT received.\n"
        f"Send USDT to: {USDT_ADDRESS}\n"
        f"Submit TXID with /txid <transaction_hash> after sending."
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"User @{update.effective_user.username} requested {amount} USDT investment."
    )

async def submit_txid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in investments or investments[user_id]["status"] != "pending":
        await update.message.reply_text("❌ No pending investment to submit TXID for.")
        return
    try:
        txid = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /txid <transaction_hash>")
        return
    investments[user_id]["txid"] = txid
    save_investments()
    await update.message.reply_text("✅ TXID submitted. Admin will verify and confirm your investment.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🟡 TXID submitted by user {user_id}: {txid}\nConfirm with /confirm {user_id}"
    )

async def profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    inv = investments.get(user_id)
    if not inv:
        await update.message.reply_text("❌ No investment or balance.")
        return
    balance = inv.get("balance", 0)
    await update.message.reply_text(f"💹 Your withdrawable balance: {balance:.2f} USDT")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    inv = investments.get(user_id)
    if not inv:
        await update.message.reply_text("❌ No investment or balance.")
        return
    balance = inv.get("balance", 0)
    if balance < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW} USDT")
        return
    try:
        wallet_address = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /withdraw <USDT BEP20 address>")
        return
    inv["withdraw_request"] = {"address": wallet_address, "amount": balance, "status": "pending"}
    save_investments()
    await update.message.reply_text("💳 Withdrawal request submitted. Admin will confirm it shortly.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💳 Withdrawal request from user {user_id}: {balance:.2f} USDT\nWallet: {wallet_address}\nConfirm with /confirm_withdraw {user_id}"
    )

# ------------------ DAILY PROFIT JOB ------------------
async def daily_profit_job(context: ContextTypes.DEFAULT_TYPE):
    for inv in investments.values():
        if inv.get("status") == "active":
            inv.setdefault("balance", 0)
            inv["balance"] += inv["amount"] * DAILY_PROFIT_PERCENT
    save_investments()
    print("✅ Daily profit added to all active investments.")

# ------------------ MAIN ------------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("txid", submit_txid))
    app.add_handler(CommandHandler("profit", profit))
    app.add_handler(CommandHandler("withdraw", withdraw))

    # Admin commands
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("confirm_withdraw", confirm_withdraw))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("user", user_detail))

    # Schedule daily profit
    app.job_queue.run_repeating(daily_profit_job, interval=86400, first=10)

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
