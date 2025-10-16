# referral_bot.py
import logging
import json
import os
from datetime import datetime, timedelta

# Telegram imports (PTB v20+ and fallback for v13)
try:
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
    )
    PTB_VERSION = 20
except ImportError:
    from telegram import Update
    from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
    PTB_VERSION = 13

# -----------------------
# Logging setup
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# -----------------------
# Constants
# -----------------------
DATA_FILE = "data.json"
PREMIUM_GROUP_LINK = "https://t.me/+ra4eSwIYWukwMjRl"
DAILY_ROI_RATE = 0.01
REFERRAL_BONUS = 20
PAIRING_BONUS = 5
MAX_DAILY_PAIRS = 10
PREMIUM_FEE = 50

# -----------------------
# Helper functions
# -----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "transactions": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def ensure_user(data, user_id):
    if str(user_id) not in data["users"]:
        data["users"][str(user_id)] = {
            "balance": 0,
            "invested": 0,
            "referrals": [],
            "referrer": None,
            "is_premium": False,
            "pending_deposit": 0,
            "pending_withdraw": 0,
            "daily_pairs": 0,
            "last_pair_date": None
        }
    return data


# -----------------------
# Command Handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    data = ensure_user(data, user_id)

    if context.args:
        referrer_id = context.args[0]
        if referrer_id != str(user_id) and referrer_id in data["users"]:
            if user_id not in data["users"][referrer_id]["referrals"]:
                data["users"][referrer_id]["referrals"].append(user_id)
                save_data(data)
                await update.message.reply_text(f"🎉 You were referred by user {referrer_id}!")
        else:
            await update.message.reply_text("Invalid referral link or self-referral not allowed.")

    save_data(data)
    await update.message.reply_text(
        "🔥 Welcome to the Premium Member Refer-to-Earn Bot! 🔥\n\n"
        "💰 Earn while helping others profit!\n"
        f"Join our referral program and unlock exclusive crypto trading signals.\n\n"
        f"✨ Membership Fee: {PREMIUM_FEE} USDT\n"
        "💎 Use /invest to start investing.\n"
        "💵 Use /withdraw to request withdrawals.\n"
        "👑 Use /joinpremium to access premium group."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Available Commands:\n\n"
        "/start [referral_id] – Start or register with a referral.\n"
        "/invest <amount> – Invest in the auto-trading bot.\n"
        "/withdraw <wallet> <amount> – Request withdrawal.\n"
        "/joinpremium – Access Premium Members Group.\n\n"
        "👑 Admin Commands:\n"
        "/approve <user_id> <amount>\n"
        "/reject <user_id>\n"
        "/approve_deposit <user_id> <amount>\n"
        "/pending_requests\n"
        "/dailyroi\n"
        "/economy"
    )


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    data = ensure_user(data, user_id)

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /invest <amount>")
        return

    amount = float(context.args[0])
    data["users"][str(user_id)]["pending_deposit"] += amount
    save_data(data)
    await update.message.reply_text(
        f"💵 Your investment of {amount} USDT is pending admin approval.\n"
        "Please wait for confirmation."
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    data = ensure_user(data, user_id)

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /withdraw <wallet_address> <amount>")
        return

    wallet, amount = context.args
    amount = float(amount)

    if amount > data["users"][str(user_id)]["balance"]:
        await update.message.reply_text("❌ Insufficient balance.")
        return

    data["users"][str(user_id)]["balance"] -= amount
    data["users"][str(user_id)]["pending_withdraw"] += amount
    save_data(data)
    await update.message.reply_text(f"✅ Withdrawal of {amount} USDT to {wallet} is pending admin approval.")


async def join_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = str(update.effective_user.id)

    user = data["users"].get(user_id, {})
    if user.get("is_premium", False):
        await update.message.reply_text(f"👑 You are already a Premium Member!\nJoin here: {PREMIUM_GROUP_LINK}")
    else:
        await update.message.reply_text(
            f"💎 Premium Membership costs {PREMIUM_FEE} USDT.\n"
            "Invest that amount to unlock premium signals.\n"
            f"After approval, you’ll get access to:\n{PREMIUM_GROUP_LINK}"
        )


# -----------------------
# Admin Commands
# -----------------------
async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /approve_deposit <user_id> <amount>")
        return

    user_id, amount = context.args
    amount = float(amount)
    data = ensure_user(data, user_id)

    user = data["users"][str(user_id)]
    user["pending_deposit"] -= amount
    user["invested"] += amount
    user["balance"] += amount * DAILY_ROI_RATE
    save_data(data)

    # Referral bonus
    if user["referrer"]:
        ref = str(user["referrer"])
        data["users"][ref]["balance"] += REFERRAL_BONUS

    # Premium activation
    if user["invested"] >= PREMIUM_FEE:
        user["is_premium"] = True

    save_data(data)
    await update.message.reply_text(f"✅ Deposit of {amount} USDT approved for {user_id}.")


async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /approve <user_id> <amount>")
        return

    user_id, amount = context.args
    amount = float(amount)
    data = load_data()
    data = ensure_user(data, user_id)

    data["users"][str(user_id)]["pending_withdraw"] -= amount
    save_data(data)
    await update.message.reply_text(f"✅ Withdrawal of {amount} USDT for {user_id} approved.")


async def reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /reject <user_id>")
        return

    user_id = context.args[0]
    data = load_data()
    data = ensure_user(data, user_id)

    amount = data["users"][str(user_id)]["pending_withdraw"]
    data["users"][str(user_id)]["pending_withdraw"] = 0
    data["users"][str(user_id)]["balance"] += amount
    save_data(data)
    await update.message.reply_text(f"❌ Withdrawal for {user_id} rejected and refunded.")


async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    deposits = [
        f"{uid}: {u['pending_deposit']} USDT"
        for uid, u in data["users"].items() if u["pending_deposit"] > 0
    ]
    withdrawals = [
        f"{uid}: {u['pending_withdraw']} USDT"
        for uid, u in data["users"].items() if u["pending_withdraw"] > 0
    ]

    msg = "📋 Pending Deposits:\n" + "\n".join(deposits or ["None"])
    msg += "\n\n📋 Pending Withdrawals:\n" + "\n".join(withdrawals or ["None"])
    await update.message.reply_text(msg)


async def daily_roi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_roi = 0
    for u in data["users"].values():
        roi = u["invested"] * DAILY_ROI_RATE
        u["balance"] += roi
        total_roi += roi
    save_data(data)
    await update.message.reply_text(f"💰 Daily ROI distributed. Total credited: {total_roi:.2f} USDT.")


async def economy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_invested = sum(u["invested"] for u in data["users"].values())
    total_balance = sum(u["balance"] for u in data["users"].values())
    total_pending = sum(u["pending_deposit"] + u["pending_withdraw"] for u in data["users"].values())

    await update.message.reply_text(
        f"📊 Economy Summary:\n\n"
        f"💵 Total Invested: {total_invested:.2f} USDT\n"
        f"💰 Total User Balances: {total_balance:.2f} USDT\n"
        f"🕐 Pending Transactions: {total_pending:.2f} USDT"
    )


# -----------------------
# Generic message handler
# -----------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 I didn’t recognize that command. Type /help for available options.")


# -----------------------
# Main function (with PTB fix)
# -----------------------
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN not found in environment variables.")

    if PTB_VERSION >= 20:
        app = ApplicationBuilder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("invest", invest))
        app.add_handler(CommandHandler("withdraw", withdraw))
        app.add_handler(CommandHandler("approve", approve_withdrawal))
        app.add_handler(CommandHandler("reject", reject_withdrawal))
        app.add_handler(CommandHandler("pending_requests", pending_requests))
        app.add_handler(CommandHandler("approve_deposit", approve_deposit))
        app.add_handler(CommandHandler("dailyroi", daily_roi))
        app.add_handler(CommandHandler("economy", economy))
        app.add_handler(CommandHandler("joinpremium", join_premium))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logging.info("✅ Bot started (PTB v20+ detected)")
        app.run_polling()
    else:
        from telegram.ext import Updater, Filters
        updater = Updater(token=TOKEN, use_context=True)
        dp = updater.dispatcher

        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("invest", invest))
        dp.add_handler(CommandHandler("withdraw", withdraw))
        dp.add_handler(CommandHandler("approve", approve_withdrawal))
        dp.add_handler(CommandHandler("reject", reject_withdrawal))
        dp.add_handler(CommandHandler("pending_requests", pending_requests))
        dp.add_handler(CommandHandler("approve_deposit", approve_deposit))
        dp.add_handler(CommandHandler("dailyroi", daily_roi))
        dp.add_handler(CommandHandler("economy", economy))
        dp.add_handler(CommandHandler("joinpremium", join_premium))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

        logging.info("✅ Bot started (PTB v13 legacy mode)")
        updater.start_polling()
        updater.idle()


if __name__ == "__main__":
    main()
