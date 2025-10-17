# referral_bot_complete.py
import logging
import json
import os
import asyncio
from datetime import datetime, timedelta
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

# Invest feature
INVEST_PROFIT_PERCENT = 1      # 1% daily
INVEST_LOCK_DAYS = 30           # 30 days lock
INVEST_ADDRESS = BNB_ADDRESS

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

# -----------------------
# Accrue daily investment profits
# -----------------------
async def accrue_invest_profits():
    while True:
        now = datetime.utcnow()
        updated = False

        for user_id, user in users.items():
            for inv in user.get("investments", []):
                last_date = datetime.fromisoformat(inv["last_profit_date"])
                days_passed = (now - last_date).days
                if days_passed >= 1:
                    profit = inv["amount"] * (INVEST_PROFIT_PERCENT / 100) * days_passed
                    user["balance"] += profit
                    inv["last_profit_date"] = now.isoformat()
                    updated = True

        if updated:
            save_data()
            logger.info("Daily investment profits credited.")

        # Wait 24 hours
        await asyncio.sleep(24 * 3600)

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
            "investments": []
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
# TXID submission
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
            text=(
                f"💳 New payment TXID submitted!\n"
                f"User ID: {user_id}\n"
                f"TXID: {txid}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    await update.message.reply_text(
        f"✅ TXID submitted successfully. Admin will verify your payment soon."
    )

# -----------------------
# Admin confirms payment
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
# Balance & stats
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    bal = user.get("balance", 0)
    earned = user.get("earned_from_referrals", 0)
    await update.message.reply_text(f"💰 Your balance: {bal} USDT\n💎 Earned from referrals: {earned} USDT")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    num_referrals = len(user.get("referrals", []))
    left = user.get("left", 0)
    right = user.get("right", 0)
    balance_amount = user.get("balance", 0)
    earned_from_referrals = user.get("earned_from_referrals", 0)
    paid = user.get("paid", False)

    msg = (
        f"📊 **Your Stats:**\n"
        f"Balance: {balance_amount} USDT\n"
        f"Earned from referrals: {earned_from_referrals} USDT\n"
        f"Direct referrals: {num_referrals}\n"
        f"Left pairs today: {left}\n"
        f"Right pairs today: {right}\n"
        f"Membership paid: {'✅' if paid else '❌'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Withdraw & process
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    # Lock investments
    locked_total = sum(
        inv["amount"] for inv in user.get("investments", [])
        if datetime.utcnow() < datetime.fromisoformat(inv["locked_until"])
    )
    available_balance = user.get("balance", 0)

    if available_balance < MIN_WITHDRAW:
        await update.message.reply_text(
            f"Your available balance is {available_balance} USDT. Minimum withdrawal is {MIN_WITHDRAW} USDT."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Please provide your BEP20 wallet address. Usage:\n/withdraw <wallet_address>"
        )
        return

    wallet_address = context.args[0]

    user["pending_withdraw"] = {
        "amount": available_balance,
        "wallet": wallet_address,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_data()

    await update.message.reply_text(
        f"✅ Withdrawal request received!\n"
        f"Amount: {available_balance} USDT\n"
        f"Wallet: {wallet_address}\n"
        "Admin will verify and process your withdrawal."
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💰 New withdrawal request!\n"
                f"User ID: {user_id}\n"
                f"Amount: {available_balance} USDT\n"
                f"Wallet: {wallet_address}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
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
# Invest commands
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /invest <amount>")
        return

    try:
        amount = float(context.args[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return

    now = datetime.utcnow()
    locked_until = now + timedelta(days=INVEST_LOCK_DAYS)
    investment = {
        "amount": amount,
        "start_date": now.isoformat(),
        "last_profit_date": now.isoformat(),
        "locked_until": locked_until.isoformat()
    }

    user.setdefault("investments", []).append(investment)
    save_data()

    await update.message.reply_text(
        f"✅ Investment recorded: {amount} USDT.\n"
        f"Send funds to:\n`{INVEST_ADDRESS}`\n"
        f"1% daily profit will go to your balance automatically.\n"
        f"Investment locked until {locked_until.date()}",
        parse_mode="Markdown"
    )

async def investstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    investments = user.get("investments", [])
    if not investments:
        await update.message.reply_text("❌ No active investments.")
        return

    msg = "📈 **Your Investments:**\n"
    for i, inv in enumerate(investments, 1):
        amount = inv["amount"]
        start = inv["start_date"].split("T")[0]
        locked_until = inv["locked_until"].split("T")[0]
        msg += f"{i}. Amount: {amount} USDT | Start: {start} | Locked until: {locked_until}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

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
        "💹 /invest <amount> - Invest funds to earn 1% daily (locked 30 days)\n"
        "📈 /investstats - View your active investments\n"
        "❓ /help - Show this menu"
    )

    if is_admin:
        help_text += (
            "\n\n--- Admin Commands ---\n"
            "/confirm <user_id> - Confirm user payment & give premium access\n"
            "/processwithdraw <user_id> - Process a withdrawal request"
        )

    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Type /help to see available commands.")

# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("⚠️ BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", process_withdraw))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("investstats", investstats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Run daily profit accrual in background
    loop = asyncio.get_event_loop()
    loop.create_task(accrue_invest_profits())

    # Run polling
    app.run_polling()
