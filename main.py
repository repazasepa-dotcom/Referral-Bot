# referral_bot_complete.py
import logging
import json
import os
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
INVEST_MIN = 50
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

def distribute_daily_profit():
    """Distribute 1% daily profit to all investments"""
    for user in users.values():
        invest = user.get("investment")
        if invest and invest.get("paid"):
            start_date = datetime.fromisoformat(invest["start_date"])
            locked_until = start_date + timedelta(days=INVEST_LOCK_DAYS)
            if datetime.utcnow() <= locked_until:
                profit = invest["amount"] * DAILY_PROFIT_PERCENT
                user["balance"] += profit
    save_data()

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
            "investment": {}
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
        "✅ TXID submitted successfully. Admin will verify your payment soon."
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
        side = "left" if users[ref_id]["left"] <= users[ref_id]["right"] else "right"
        if users[ref_id][side] < MAX_PAIRS_PER_DAY:
            users[ref_id][side] += 1
            users[ref_id]["balance"] += PAIRING_BONUS
            users[ref_id]["earned_from_referrals"] += PAIRING_BONUS
    save_data()

    await update.message.reply_text(
        f"✅ User {target_user_id} confirmed as paid.\nTXID: {txid}\n"
        f"Bonuses credited to referrer.\n\nPremium channel link:\n{PREMIUM_GROUP}"
    )

# -----------------------
# Investment command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text(f"Usage: /invest <amount> <TXID>\nMinimum investment: {INVEST_MIN} USDT")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text(f"❌ Invalid amount. Minimum investment: {INVEST_MIN} USDT")
        return
    txid = context.args[1]
    if amount < INVEST_MIN:
        await update.message.reply_text(f"❌ Minimum investment is {INVEST_MIN} USDT.")
        return
    if user.get("investment", {}).get("paid"):
        await update.message.reply_text("✅ You already have an active investment.")
        return
    user["investment"] = {
        "amount": amount,
        "paid": False,
        "txid": txid,
        "start_date": datetime.utcnow().isoformat()
    }
    save_data()
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💹 New investment submitted!\nUser ID: {user_id}\nAmount: {amount} USDT\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
    daily_profit = amount * DAILY_PROFIT_PERCENT
    invest_text = (
        f"✅ Investment submitted!\n\n"
        f"💰 Amount: {amount} USDT\n"
        f"🏦 Send USDT here: `{BNB_ADDRESS}`\n\n"
        f"⏳ Locked for {INVEST_LOCK_DAYS} days\n"
        f"📈 Daily Profit: {daily_profit:.2f} USDT added to withdrawable balance\n"
        f"💎 Referral rewards also added to balance\n\n"
        "Admin will confirm your investment soon. 🚀"
    )
    await update.message.reply_text(invest_text, parse_mode="Markdown")

# -----------------------
# FAQ command
# -----------------------
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    faq_text = (
        "💡 **Bot FAQ & Earning Opportunities** 💡\n\n"
        f"1️⃣ Auto-Trading Investment 💹\n"
        f"• Minimum: {INVEST_MIN} USDT\n"
        f"• Deposit: `{BNB_ADDRESS}`\n"
        "• Submit TXID: `/invest <amount> <TXID>`\n"
        f"• Locked: {INVEST_LOCK_DAYS} days\n"
        "• Earn 1% daily profit added to withdrawable balance\n\n"
        "2️⃣ Referral Rewards 🤝\n"
        "• Share your referral link `/start <your_id>`\n"
        "• Direct bonus: 20 USDT\n"
        "• Pairing bonus: up to 50 USDT/day\n\n"
        "3️⃣ Premium Membership ✨\n"
        "• Early coin alerts, 2-5 daily signals\n"
        "• Auto trading bot\n"
        "• Exclusive 1-3 coins daily\n\n"
        "4️⃣ Withdrawals 🏦\n"
        f"• Minimum withdrawal: {MIN_WITHDRAW} USDT\n"
        "• Withdraw: `/withdraw <wallet>`"
    )
    await update.message.reply_text(faq_text, parse_mode="Markdown")

# -----------------------
# Balance & stats
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
    await update.message.reply_text(f"💰 Balance: {bal} USDT\n💎 Earned from referrals: {earned} USDT")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    referrals = len(user.get("referrals", []))
    left = user.get("left", 0)
    right = user.get("right", 0)
    bal = user.get("balance", 0)
    earned = user.get("earned_from_referrals", 0)
    paid = user.get("paid", False)
    msg = (
        f"📊 **Stats:**\n"
        f"Balance: {bal} USDT\n"
        f"Earned from referrals: {earned} USDT\n"
        f"Direct referrals: {referrals}\n"
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
    bal = user.get("balance", 0)
    if bal < MIN_WITHDRAW:
        await update.message.reply_text(f"Balance {bal} USDT. Minimum withdrawal: {MIN_WITHDRAW} USDT.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /withdraw <BEP20_wallet>")
        return
    wallet = context.args[0]
    user["pending_withdraw"] = {
        "amount": bal,
        "wallet": wallet,
        "timestamp": datetime.utcnow().isoformat()
    }
    save_data()
    await update.message.reply_text(f"✅ Withdrawal request received!\nAmount: {bal} USDT\nWallet: {wallet}")
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New withdrawal request!\nUser ID: {user_id}\nAmount: {bal} USDT\nWallet: {wallet}"
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
    uid = context.args[0]
    user = users.get(uid)
    if not user or "pending_withdraw" not in user:
        await update.message.reply_text("❌ No pending withdrawal for this user.")
        return
    pending = user.pop("pending_withdraw")
    amount = pending["amount"]
    user["balance"] -= amount
    save_data()
    try:
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"✅ Withdrawal processed!\nAmount: {amount} USDT"
        )
        await update.message.reply_text(f"✅ User {uid} notified.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to notify user: {e}")

# -----------------------
# Help & unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    help_text = (
        "📌 Commands:\n"
        "/start - Register & get referral link\n"
        "/balance - Check balance\n"
        "/stats - View stats\n"
        "/withdraw <wallet> - Withdraw funds\n"
        "/pay <TXID> - Submit membership payment\n"
        "/invest <amount> <TXID> - Invest in auto-trading\n"
        "/faq - Learn about earning opportunities\n"
        "/help - Show this menu"
    )
    if is_admin:
        help_text += (
            "\n\n--- Admin ---\n"
            "/confirm <user_id> - Confirm payment\n"
            "/confirminvest <user_id> - Confirm investment\n"
            "/processwithdraw <user_id> - Process withdrawals"
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
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Run polling
    app.run_polling()
