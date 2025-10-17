# referral_bot_full.py
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
DATA_FILE = "users.json"
META_FILE = "meta.json"

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
INVEST_LOCK_DAYS = 30
DAILY_PROFIT_PERCENT = 0.01

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
            invest_date = datetime.fromisoformat(user["investment_date"])
            days_passed = (datetime.utcnow() - invest_date).days
            if days_passed < INVEST_LOCK_DAYS:
                profit = user["investment_balance"] * DAILY_PROFIT_PERCENT
                user["profit_earned"] += profit
                user["balance"] += profit  # Withdrawable profit
    save_data()
    logger.info("Daily profit added to all investments.")

# -----------------------
# Command handlers
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
        "🚀 1-3 special signals daily in premium channel\n"
    )

    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BNB Smart Chain BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"Share your referral link to earn bonuses after your friends pay:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# Payment
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    if user.get("paid"):
        await update.message.reply_text("✅ You are already confirmed as paid.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /pay <transaction_id>")
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
        logger.error(f"Failed to notify admin: {e}")

    await update.message.reply_text(
        f"✅ TXID submitted successfully. Admin will verify your payment soon."
    )

# -----------------------
# Confirm payment
# -----------------------
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /confirm <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    if user.get("paid"):
        await update.message.reply_text("User is already marked as paid.")
        return

    txid = user.get("txid")
    if not txid:
        await update.message.reply_text("❌ User has not submitted a TXID yet.")
        return

    user["paid"] = True
    save_data()

    # Credit referrer bonuses
    ref_id = user.get("referrer")
    if ref_id:
        users[ref_id]["balance"] += DIRECT_BONUS
        users[ref_id]["earned_from_referrals"] += DIRECT_BONUS

        # Pairing bonus logic
        if users[ref_id]["left"] <= users[ref_id]["right"]:
            side = "left"
        else:
            side = "right"

        if users[ref_id][side] < MAX_PAIRS_PER_DAY:
            users[ref_id][side] += 1
            users[ref_id]["balance"] += PAIRING_BONUS
            users[ref_id]["earned_from_referrals"] += PAIRING_BONUS

    save_data()

    await update.message.reply_text(
        f"✅ User {target_user_id} confirmed as paid.\nTXID: {txid}\n"
        f"Bonuses credited to referrer.\n\n"
        f"Here is your premium signals channel link:\n{PREMIUM_GROUP}"
    )

# -----------------------
# Investment: user submit TXID
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ Register first with /start")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /invest <TXID>")
        return

    txid = context.args[0]
    user["investment_txid"] = txid
    save_data()

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💳 New investment submitted!\nUser: {user_id}\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await update.message.reply_text(
        f"✅ Investment TXID submitted. Admin will verify and confirm."
    )

# -----------------------
# Admin confirms investment
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /confirminvest <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or not user.get("investment_txid"):
        await update.message.reply_text("❌ No investment submitted.")
        return

    user["investment_confirmed"] = True
    # Optionally set real amount here after verification
    user["investment_balance"] += 0  # Update after real deposit check
    user["investment_date"] = datetime.utcnow().isoformat()
    save_data()

    await update.message.reply_text(f"✅ Investment confirmed for {target_user_id}")
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text="✅ Your investment has been confirmed! Funds are locked for 30 days."
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

# -----------------------
# Balance & Stats
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    bal = user.get("balance", 0)
    earned = user.get("earned_from_referrals", 0)
    invest_bal = user.get("investment_balance", 0)
    profit = user.get("profit_earned", 0)

    await update.message.reply_text(
        f"💰 Balance: {bal} USDT\n"
        f"💎 Earned from referrals: {earned} USDT\n"
        f"📈 Investment balance: {invest_bal} USDT\n"
        f"💹 Profit earned: {profit:.2f} USDT"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    days_left = 0
    if user.get("investment_confirmed") and user.get("investment_date"):
        invest_date = datetime.fromisoformat(user["investment_date"])
        days_passed = (datetime.utcnow() - invest_date).days
        days_left = max(INVEST_LOCK_DAYS - days_passed, 0)

    msg = (
        f"📊 **Your Stats:**\n"
        f"Balance: {user.get('balance',0)} USDT\n"
        f"Earned from referrals: {user.get('earned_from_referrals',0)} USDT\n"
        f"Direct referrals: {len(user.get('referrals',[]))}\n"
        f"Left pairs today: {user.get('left',0)}\n"
        f"Right pairs today: {user.get('right',0)}\n"
        f"Membership paid: {'✅' if user.get('paid') else '❌'}\n"
        f"Investment balance: {user.get('investment_balance',0)} USDT\n"
        f"Profit earned: {user.get('profit_earned',0):.2f} USDT\n"
        f"Investment confirmed: {'✅' if user.get('investment_confirmed') else '❌'}\n"
        f"Days until investment unlock: {days_left}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# My Investment Quick View
# -----------------------
async def myinvestment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    if not user.get("investment_confirmed"):
        await update.message.reply_text("❌ You have no confirmed investment yet.")
        return

    invest_bal = user.get("investment_balance", 0)
    profit = user.get("profit_earned", 0)
    invest_date = datetime.fromisoformat(user["investment_date"])
    days_passed = (datetime.utcnow() - invest_date).days
    days_left = max(INVEST_LOCK_DAYS - days_passed, 0)

    msg = (
        f"📈 **Your Investment Summary:**\n"
        f"Investment balance: {invest_bal} USDT\n"
        f"Profit earned: {profit:.2f} USDT\n"
        f"Days until unlock: {days_left}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Withdraw & Admin Process
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    balance_amount = user.get("balance", 0)
    if balance_amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"Your balance is {balance_amount} USDT. Minimum withdrawal is {MIN_WITHDRAW} USDT."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Provide your BEP20 wallet: /withdraw <wallet>"
        )
        return

    wallet_address = context.args[0]
    user["pending_withdraw"] = {
        "amount": balance_amount,
        "wallet": wallet_address,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_data()

    await update.message.reply_text(
        f"✅ Withdrawal request received!\n"
        f"Amount: {balance_amount} USDT\nWallet: {wallet_address}\nAdmin will process."
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 Withdrawal request!\nUser: {user_id}\nAmount: {balance_amount} USDT\nWallet: {wallet_address}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /processwithdraw <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or "pending_withdraw" not in user:
        await update.message.reply_text("❌ No pending withdrawal.")
        return

    pending = user.pop("pending_withdraw")
    amount = pending["amount"]
    user["balance"] -= amount
    save_data()

    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=f"✅ Your withdrawal of {amount} USDT has been processed."
        )
        await update.message.reply_text(f"✅ User {target_user_id} notified.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to notify user: {e}")

# -----------------------
# Help & Unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID

    help_text = (
        "📌 Commands:\n"
        "/start - Register & get referral link\n"
        "/balance - Check balance & profits\n"
        "/stats - View full stats\n"
        "/myinvestment - View investment summary\n"
        "/withdraw <BEP20> - Request withdrawal\n"
        "/pay <TXID> - Submit membership payment\n"
        "/invest <TXID> - Submit investment TXID\n"
        "/help - Show this menu"
    )

    if is_admin:
        help_text += (
            "\n--- Admin ---\n"
            "/confirm <user_id> - Confirm membership payment\n"
            "/confirminvest <user_id> - Confirm investment\n"
            "/processwithdraw <user_id> - Process withdrawal"
        )

    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Type /help for list.")

# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("⚠️ BOT_TOKEN not set!")

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", process_withdraw))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirminvest", confirm_invest))
    app.add_handler(CommandHandler("myinvestment", myinvestment))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Scheduler for daily reset and profit
    scheduler = AsyncIOScheduler()
    scheduler.add_job(reset_pairing_if_needed, 'cron', hour=0, minute=0)
    scheduler.add_job(add_daily_profit, 'cron', hour=0, minute=5)
    scheduler.start()

    # Run bot
    app.run_polling()
