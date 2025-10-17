import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# -----------------------
# CONFIGURATION
# -----------------------
DATA_FILE = "bot_data.json"
ADMIN_ID = 123456789  # Replace with your Telegram user ID
BNB_ADDRESS = "0xYourUSDTBEP20AddressHere"
INVEST_LOCK_DAYS = 30
MIN_INVEST = 50
MIN_WITHDRAW = 20

# -----------------------
# LOGGING
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# UTILITIES
# -----------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=2)

users = load_data()

# -----------------------
# START Command
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in users:
        ref = context.args[0] if context.args else None
        users[user_id] = {
            "ref": ref,
            "paid": False,
            "balance": 0,
            "investment": {},
            "referrals": []
        }
        if ref and ref in users:
            users[ref]["referrals"].append(user_id)
        save_data()

    await update.message.reply_text(
        "👋 Welcome to *Auto-Trading Bot*!\n\n"
        "💼 Earn daily profits through our auto-trading system and referral bonuses.\n"
        "💳 To join premium and start earning, pay 50 USDT to:\n"
        f"`{BNB_ADDRESS}` (BEP20)\n\n"
        "Then submit your TXID using /pay <txid>.\n\n"
        f"📢 Your referral link:\nhttps://t.me/{context.bot.username}?start={user_id}",
        parse_mode="Markdown"
    )

# -----------------------
# PAY Command
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ Please provide your transaction ID (TXID).\nUsage: /pay <txid>")
        return
    txid = context.args[0]
    users[user_id]["txid"] = txid
    save_data()
    await update.message.reply_text("✅ TXID received! Please wait for admin confirmation.")

# -----------------------
# INVEST Command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text("💹 Usage: /invest <amount> <txid>")
        return
    amount = float(context.args[0])
    txid = context.args[1]

    if amount < MIN_INVEST:
        await update.message.reply_text(f"⚠️ Minimum investment is {MIN_INVEST} USDT.")
        return

    users[user_id]["investment"] = {
        "amount": amount,
        "txid": txid,
        "paid": False,
        "start_date": None
    }
    save_data()

    await update.message.reply_text(
        f"📩 Investment request submitted!\n"
        f"💰 Amount: {amount} USDT\n"
        f"🔗 TXID: `{txid}`\n"
        f"⏳ Waiting for admin confirmation.",
        parse_mode="Markdown"
    )

# -----------------------
# CONFIRM INVEST (Admin)
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /confirm_invest <user_id>")
        return

    user_id = context.args[0]
    if user_id not in users or "investment" not in users[user_id]:
        await update.message.reply_text("User or investment not found.")
        return

    users[user_id]["investment"]["paid"] = True
    users[user_id]["investment"]["start_date"] = datetime.utcnow().isoformat()
    save_data()

    await update.message.reply_text(f"✅ Investment confirmed for user {user_id}.")
    await context.bot.send_message(chat_id=int(user_id),
        text="🎉 Your investment is confirmed!\n"
             "💹 You’ll earn 1% profit daily for 30 days.\n"
             "🔒 Investment is now locked.")

# -----------------------
# BALANCE Command
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id, {})
    invest = user.get("investment", {})
    bal = user.get("balance", 0)

    if invest.get("paid"):
        start_date = datetime.fromisoformat(invest["start_date"])
        unlock_date = start_date + timedelta(days=INVEST_LOCK_DAYS)
        days_left = max((unlock_date - datetime.utcnow()).days, 0)
        invest_text = (
            f"💹 Investment: {invest['amount']:.2f} USDT\n"
            f"🔒 Locked for {INVEST_LOCK_DAYS} days\n"
            f"🕒 {days_left} days remaining"
        )
    elif invest.get("amount"):
        invest_text = f"💹 Pending Investment: {invest['amount']} USDT (awaiting admin confirmation)"
    else:
        invest_text = "💹 No active investment."

    await update.message.reply_text(
        f"💰 Balance: {bal:.2f} USDT\n{invest_text}"
    )

# -----------------------
# STATS Command
# -----------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id, {})
    refs = len(user.get("referrals", []))
    balance = user.get("balance", 0)
    invest = user.get("investment", {})
    paid = user.get("paid", False)

    if invest.get("paid"):
        start = datetime.fromisoformat(invest["start_date"])
        unlock = start + timedelta(days=INVEST_LOCK_DAYS)
        left = max((unlock - datetime.utcnow()).days, 0)
        invest_info = f"💹 Investment: {invest['amount']} USDT\n🔒 Locked: {INVEST_LOCK_DAYS} days\n🕒 {left} days left"
    else:
        invest_info = "💹 No confirmed investment yet."

    await update.message.reply_text(
        f"📊 Your Stats:\n\n"
        f"👥 Referrals: {refs}\n"
        f"💰 Balance: {balance:.2f} USDT\n"
        f"🏦 Premium: {'✅ Yes' if paid else '❌ No'}\n"
        f"{invest_info}"
    )

# -----------------------
# WITHDRAW Command
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("💸 Usage: /withdraw <wallet_address>")
        return
    wallet = context.args[0]
    user = users.get(user_id, {})
    if user.get("balance", 0) < MIN_WITHDRAW:
        await update.message.reply_text(f"⚠️ Minimum withdrawal is {MIN_WITHDRAW} USDT.")
        return
    await update.message.reply_text(f"✅ Withdrawal request sent!\n💼 Wallet: `{wallet}`", parse_mode="Markdown")

# -----------------------
# FAQ Command
# -----------------------
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *Frequently Asked Questions* 💬\n\n"
        "💹 *Auto-Trading Investment Feature*\n\n"
        "🚀 Invest USDT to join auto-trading and earn *1% profit daily* once confirmed by admin!\n\n"
        f"💳 Deposit to: `{BNB_ADDRESS}` (BEP20)\n"
        "📥 Then use `/invest <amount> <txid>` to submit your transaction.\n\n"
        "🔒 Investments are locked for 30 days.\n"
        "💰 Profits (1% daily) go straight to your withdrawable balance!\n"
        "🎁 You also earn referral bonuses when others join using your link!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# -----------------------
# HELP Command
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Bot Commands Overview*\n\n"
        "💬 General:\n"
        "• /start - Start & get your referral link\n"
        "• /faq - Learn how to earn\n"
        "• /help - Show all commands\n\n"
        "💰 Earning:\n"
        "• /pay <txid> - Confirm membership payment\n"
        "• /invest <amount> <txid> - Invest (min 50 USDT)\n"
        "• /balance - View balance & lock info\n"
        "• /stats - Check investment & referrals\n"
        "• /withdraw <wallet> - Request withdrawal\n\n"
        "🎁 Referral:\n"
        "Invite friends using your link from /start and earn rewards!\n\n"
        "🧑‍💼 Contact admin for payment or support help."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# -----------------------
# ADMIN: DISTRIBUTE PROFIT
# -----------------------
def distribute_daily_profit():
    for user_id, user in users.items():
        invest = user.get("investment", {})
        if invest.get("paid"):
            amount = invest["amount"]
            profit = amount * 0.01
            user["balance"] = user.get("balance", 0) + profit
    save_data()

async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    distribute_daily_profit()
    await update.message.reply_text("✅ Daily 1% profits distributed to all investors!")

# -----------------------
# MAIN ENTRY POINT
# -----------------------
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("❌ BOT_TOKEN not found in environment variables.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # Public Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("help", help_command))

    # Admin Commands
    app.add_handler(CommandHandler("confirm_invest", confirm_invest))
    app.add_handler(CommandHandler("distribute", distribute))

    logger.info("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
