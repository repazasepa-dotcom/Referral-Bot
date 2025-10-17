# referral_bot_complete.py
import logging
import warnings
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
# Suppress pkg_resources warning
# -----------------------
warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

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

# Investment constants
INVESTMENT_LOCK_DAYS = 30
DAILY_PROFIT_PERCENT = 1

# -----------------------
# Helper functions
# -----------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=4)

def save_meta():
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=4)

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
        invest_balance = user.get("investment_balance", 0)
        if invest_balance > 0:
            profit = invest_balance * DAILY_PROFIT_PERCENT / 100
            user["balance"] += profit
            user["earned_from_referrals"] += profit
    save_data()
    logger.info("Daily profits added to all investors.")

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
            "investment_start": None,
            "pending_invest": None,
            "pending_withdraw": None
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
        "   (these coins will pump within 24 hours or very short duration)\n\n"
    )

    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BNB Smart Chain BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"Share your referral link to earn bonuses after your friends pay:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# Payment submission
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /pay <transaction_id>")
        return

    txid = context.args[0]

    if user.get("pending_invest"):
        user["pending_invest"]["txid"] = txid
        msg_type = "investment"
    else:
        if user.get("paid"):
            await update.message.reply_text("✅ You are already confirmed as paid.")
            return
        user["txid"] = txid
        msg_type = "membership"

    save_data()

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💳 New {msg_type} TXID submitted!\n"
                f"User ID: {user_id}\n"
                f"TXID: {txid}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await update.message.reply_text(
        f"✅ TXID submitted successfully for {msg_type}. Admin will verify your payment soon."
    )

# -----------------------
# Confirm membership
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

    # Referrer bonuses
    ref_id = user.get("referrer")
    if ref_id:
        users[ref_id]["balance"] += DIRECT_BONUS
        users[ref_id]["earned_from_referrals"] += DIRECT_BONUS

        side = "left" if users[ref_id]["left"] <= users[ref_id]["right"] else "right"
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
# Confirm investment
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can confirm.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /confirminvest <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or not user.get("pending_invest"):
        await update.message.reply_text("❌ No pending investment for this user.")
        return

    invest_data = user.pop("pending_invest")
    user["investment_balance"] += invest_data["amount"]
    user["investment_start"] = datetime.utcnow().isoformat()
    save_data()

    await update.message.reply_text(f"✅ User {target_user_id} investment confirmed: {invest_data['amount']} USDT")

# -----------------------
# Investment command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    
    if not user:
        await update.message.reply_text("❌ Use /start first to register.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /invest <amount>")
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return

    user["pending_invest"] = {
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_data()

    await update.message.reply_text(
        f"💳 Pending investment recorded: {amount} USDT.\n"
        f"Send this amount to:\n`{BNB_ADDRESS}`\n"
        f"Then submit TXID with /pay <TXID>"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New pending investment!\nUser ID: {user_id}\nAmount: {amount} USDT"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# -----------------------
# Balance
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    bal = user.get("balance", 0)
    invest = user.get("investment_balance", 0)
    earned = user.get("earned_from_referrals", 0)
    await update.message.reply_text(
        f"💰 Balance: {bal} USDT\n"
        f"💎 Earned from referrals/profit: {earned} USDT\n"
        f"📈 Investment balance: {invest} USDT"
    )

# -----------------------
# Stats
# -----------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    num_referrals = len(user.get("referrals", []))
    left = user.get("left", 0)
    right = user.get("right", 0)
    balance_amount = user.get("balance", 0)
    earned_from_referrals = user.get("earned_from_referrals", 0)
    invest_balance = user.get("investment_balance", 0)
    paid = user.get("paid", False)

    msg = (
        f"📊 **Your Stats:**\n"
        f"Balance: {balance_amount} USDT\n"
        f"Investment: {invest_balance} USDT\n"
        f"Earned from referrals/profit: {earned_from_referrals} USDT\n"
        f"Direct referrals: {num_referrals}\n"
        f"Left pairs today: {left}\n"
        f"Right pairs today: {right}\n"
        f"Membership paid: {'✅' if paid else '❌'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Withdraw
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
            "Please provide your BEP20 wallet address. Usage:\n/withdraw <wallet_address>"
        )
        return

    wallet_address = context.args[0]

    # Save pending withdrawal
    user["pending_withdraw"] = {
        "amount": balance_amount,
        "wallet": wallet_address,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_data()

    await update.message.reply_text(
        f"✅ Withdrawal request received!\n"
        f"Amount: {balance_amount} USDT\n"
        f"Wallet: {wallet_address}\n"
        "Admin will verify and process your withdrawal."
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💰 New withdrawal request!\n"
                f"User ID: {user_id}\n"
                f"Amount: {balance_amount} USDT\n"
                f"Wallet: {wallet_address}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# -----------------------
# Process withdrawal (admin)
# -----------------------
async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Only admin can use this command.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /processwithdraw <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or "pending_withdraw" not in user:
        await update.message.reply_text("❌ No pending withdrawal for this user.")
        return

    pending = user.pop("pending_withdraw")
    amount = pending["amount"]
    user["balance"] -= amount
    save_data()

    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=(
                f"✅ Your withdrawal request has been processed!\n"
                f"Amount: {amount} USDT\n"
                "Funds will arrive in your BEP20 wallet shortly."
            )
        )
        await update.message.reply_text(f"✅ User {target_user_id} has been notified.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to notify user: {e}")

# -----------------------
# Help & unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID

    help_text = (
        "📌 Available Commands:\n\n"
        "✨ /start - Register and see referral link & benefits\n"
        "💵 /balance - Check your current balance\n"
        "📊 /stats - View your referral stats\n"
        "🏦 /withdraw <BEP20_wallet> - Request withdrawal (min 20 USDT)\n"
        "💳 /pay <TXID> - Submit your payment transaction ID\n"
        "💰 /invest <amount> - Make a new investment\n"
        "❓ /help - Show this menu"
    )

    if is_admin:
        help_text += (
            "\n\n--- Admin Commands ---\n"
            "/confirm <user_id> - Confirm user membership\n"
            "/confirminvest <user_id> - Confirm user investment\n"
            "/processwithdraw <user_id> - Process a withdrawal request"
        )

    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Type /help to see available commands.")

# -----------------------
# Main startup
# -----------------------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("⚠️ BOT_TOKEN environment variable not set!")

    # Build polling app
    app = ApplicationBuilder().token(TOKEN).build_polling()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("confirminvest", confirm_invest))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", process_withdraw))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(add_daily_profit, 'cron', hour=0, minute=0)
    scheduler.start()
    logger.info("Scheduler started: Daily profit job added.")

    # Send startup message to admin
    import asyncio
    async def send_startup_message():
        try:
            await app.bot.send_message(chat_id=ADMIN_ID, text="✅ Bot is live and running!")
            logger.info("Startup message sent to admin.")
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")
    asyncio.get_event_loop().create_task(send_startup_message())

    logger.info("Bot started successfully with polling.")
