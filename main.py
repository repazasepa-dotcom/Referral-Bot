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
        logger.info("🌞 Daily pairing counts reset.")

def distribute_daily_profit():
    """Distribute 1% daily profit to all active investments"""
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
        "🔥 **Premium Membership Benefits** 🔥\n\n"
        "🚀 Get coin names before pump\n"
        "📈 Guidance on buy & sell targets\n"
        "💎 Receive 2-5 daily signals\n"
        "🤖 Auto trading by bot\n"
        "✨ 1-3 special signals daily (coins that pump quickly)\n\n"
    )
    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BNB Smart Chain BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"🔗 Share your referral link to earn bonuses:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# Payment submission
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ You are already confirmed as paid.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("💳 Usage: /pay <transaction_id>")
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
    await update.message.reply_text("✅ TXID submitted successfully. Admin will verify soon. ⏳")

# -----------------------
# Admin confirms payment
# -----------------------
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("✅ Usage: /confirm <user_id>")
        return
    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user:
        await update.message.reply_text("❌ User not found.")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ User already paid.")
        return
    txid = user.get("txid")
    if not txid:
        await update.message.reply_text("❌ User has not submitted TXID.")
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
        f"✅ User {target_user_id} confirmed as paid!\nTXID: {txid}\n"
        f"🎁 Bonuses credited to referrer.\n\nPremium channel link: {PREMIUM_GROUP}"
    )

# -----------------------
# Investment
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text(f"💹 Usage: /invest <amount> <TXID>\nMinimum: {INVEST_MIN} USDT")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text(f"❌ Invalid amount. Minimum: {INVEST_MIN} USDT")
        return
    txid = context.args[1]
    if amount < INVEST_MIN:
        await update.message.reply_text(f"❌ Minimum investment: {INVEST_MIN} USDT")
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
            text=f"💹 New investment!\nUser ID: {user_id}\nAmount: {amount} USDT\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
    daily_profit = amount * DAILY_PROFIT_PERCENT
    await update.message.reply_text(
        f"✅ Investment submitted!\n💰 Amount: {amount} USDT\n🏦 Send USDT to: `{BNB_ADDRESS}`\n"
        f"⏳ Locked for {INVEST_LOCK_DAYS} days\n📈 Daily Profit: {daily_profit:.2f} USDT\n"
        f"💎 Referral rewards also increase your balance\nAdmin will confirm soon! 🚀",
        parse_mode="Markdown"
    )

# -----------------------
# Admin: Distribute daily profit
# -----------------------
async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    distribute_daily_profit()
    await update.message.reply_text("✅ Daily profit has been distributed to all active investments! 💹")

# -----------------------
# User: balance, stats, withdraw
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

    invest_info = ""
    invest = user.get("investment", {})
    if invest.get("paid"):
        start_date = datetime.fromisoformat(invest["start_date"])
        locked_until = start_date + timedelta(days=INVEST_LOCK_DAYS)
        days_left = max((locked_until - datetime.utcnow()).days, 0)
        invest_info = (
            f"\n💹 Investment: {invest['amount']:.2f} USDT"
            f"\n⏳ Locked for {INVEST_LOCK_DAYS} days"
            f"\n🕒 Days remaining: {days_left} days"
        )

    await update.message.reply_text(
        f"💰 Balance: {bal:.2f} USDT\n💎 Earned from referrals: {earned:.2f} USDT"
        f"{invest_info}"
    )

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
    paid = user.get("paid", False)

    invest_info = ""
    invest = user.get("investment", {})
    if invest.get("paid"):
        start_date = datetime.fromisoformat(invest["start_date"])
        locked_until = start_date + timedelta(days=INVEST_LOCK_DAYS)
        days_left = max((locked_until - datetime.utcnow()).days, 0)
        invest_info = (
            f"\n💹 Investment: {invest['amount']:.2f} USDT"
            f"\n⏳ Locked for {INVEST_LOCK_DAYS} days"
            f"\n🕒 Days remaining: {days_left} days"
        )

    msg = (
        f"📊 **Your Stats:**\n"
        f"Balance: {balance_amount:.2f} USDT\n"
        f"Earned from referrals: {earned_from_referrals:.2f} USDT\n"
        f"Direct referrals: {num_referrals}\n"
        f"Left pairs today: {left}\n"
        f"Right pairs today: {right}\n"
        f"Membership paid: {'✅' if paid else '❌'}"
        f"{invest_info}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# FAQ
# -----------------------
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 **FAQ - Earning Opportunities**\n\n"
        "💹 **Invest in Auto-Trading:**\n"
        f"• Minimum: {INVEST_MIN} USDT\n"
        f"• Send USDT to `{BNB_ADDRESS}` and submit TXID\n"
        f"• Locked for {INVEST_LOCK_DAYS} days ⏳\n"
        f"• Earn 1% daily profit 📈 added to balance\n"
        "• Referral bonuses also increase withdrawable balance\n\n"
        "🚀 **Referral Bonuses:**\n"
        "• Invite friends via your link\n"
        "• Earn direct + pairing bonuses 💎\n"
        "• Bonuses go directly to your balance"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Help & unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    help_text = (
        "📌 **Commands:**\n\n"
        "✨ /start - Register & see referral link & benefits\n"
        "💵 /balance - Check balance\n"
        "📊 /stats - View your stats\n"
        "🏦 /withdraw <wallet> - Request withdrawal\n"
        "💳 /pay <TXID> - Submit payment\n"
        "💹 /invest <amount> <TXID> - Invest in Auto trading\n"
        "❓ /faq - Learn about earning opportunities"
    )
    if is_admin:
        help_text += (
            "\n\n--- Admin Commands ---\n"
            "/confirm <user_id> - Confirm payment\n"
            "/processwithdraw <user_id> - Process withdrawal\n"
            "/distribute - Distribute daily profit"
        )
    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Type /help to see all commands.")

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
    app.add_handler(CommandHandler("distribute", distribute))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Run polling
    app.run_polling()
