import logging
import json
import os
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# -----------------------
# Logging setup
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
        logger.info("✅ Daily pairing counts reset.")
        return True
    return False

# -----------------------
# Commands
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
            "proof": None
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
        "🚀 Buy & sell target guidance\n"
        "🚀 2–5 daily signals\n"
        "🚀 Auto trading bot integration\n"
        "🚀 1–3 VIP premium signals (coins that pump within 24h)\n\n"
    )

    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BNB Smart Chain BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"Then send `/pay <TXID>` or upload a screenshot proof.\n\n"
        f"Refer friends and earn bonuses!\nYour link:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# Payment proof or TXID
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    # Payment proof via photo
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        proof_path = f"proof_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
        await file.download_to_drive(proof_path)
        user["proof"] = proof_path
        save_data()

        await update.message.reply_text("✅ Payment screenshot received! Admin will verify soon.")
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=open(proof_path, "rb"),
                caption=f"🧾 Payment proof from user {user_id}"
            )
        except Exception as e:
            logger.error(f"Error sending proof to admin: {e}")
        return

    # Payment proof via TXID
    if not context.args:
        await update.message.reply_text("Usage: `/pay <TXID>` or send a screenshot.", parse_mode="Markdown")
        return

    txid = context.args[0]
    user["txid"] = txid
    save_data()

    await update.message.reply_text("✅ TXID submitted! Admin will verify your payment soon.")
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💳 New TXID from user {user_id}\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Error sending TXID to admin: {e}")

# -----------------------
# Admin confirm payment
# -----------------------
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /confirm <user_id>")
        return

    target_id = context.args[0]
    user = users.get(target_id)
    if not user:
        await update.message.reply_text("❌ User not found.")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ Already confirmed.")
        return

    user["paid"] = True
    save_data()

    # Reward referrer
    ref_id = user.get("referrer")
    if ref_id and ref_id in users:
        users[ref_id]["balance"] += DIRECT_BONUS
        users[ref_id]["earned_from_referrals"] += DIRECT_BONUS

        side = "left" if users[ref_id]["left"] <= users[ref_id]["right"] else "right"
        if users[ref_id][side] < MAX_PAIRS_PER_DAY:
            users[ref_id][side] += 1
            users[ref_id]["balance"] += PAIRING_BONUS
            users[ref_id]["earned_from_referrals"] += PAIRING_BONUS

    save_data()

    await update.message.reply_text(
        f"✅ User {target_id} confirmed.\nBonuses credited.\n\nPremium group:\n{PREMIUM_GROUP}"
    )

# -----------------------
# Balance / Stats
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    await update.message.reply_text(
        f"💰 Balance: {user.get('balance', 0)} USDT\n💎 Earned: {user.get('earned_from_referrals', 0)} USDT"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    msg = (
        f"📊 **Stats:**\n"
        f"Balance: {user.get('balance', 0)} USDT\n"
        f"Earned: {user.get('earned_from_referrals', 0)} USDT\n"
        f"Direct referrals: {len(user.get('referrals', []))}\n"
        f"Left pairs: {user.get('left', 0)} / Right pairs: {user.get('right', 0)}\n"
        f"Paid: {'✅' if user.get('paid') else '❌'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Withdraw system
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return

    bal = user.get("balance", 0)
    if bal < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Min withdraw {MIN_WITHDRAW} USDT. Your balance: {bal}")
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

    await update.message.reply_text(
        f"✅ Withdraw request received!\nAmount: {bal} USDT\nWallet: {wallet}\nAdmin will process soon."
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💰 Withdraw request from {user_id}\nAmount: {bal} USDT\nWallet: {wallet}"
    )

async def processwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /processwithdraw <user_id>")
        return

    uid = context.args[0]
    user = users.get(uid)
    if not user or "pending_withdraw" not in user:
        await update.message.reply_text("❌ No pending withdrawal.")
        return

    pending = user.pop("pending_withdraw")
    user["balance"] -= pending["amount"]
    save_data()

    await context.bot.send_message(
        chat_id=int(uid),
        text=f"✅ Your withdrawal ({pending['amount']} USDT) is processed!"
    )
    await update.message.reply_text(f"✅ Withdrawal completed for user {uid}.")

# -----------------------
# Help / Unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID

    help_text = (
        "📘 Commands:\n"
        "/start - Register / Get referral link\n"
        "/pay <TXID> or send screenshot - Submit payment\n"
        "/balance - Check balance\n"
        "/stats - View your stats\n"
        "/withdraw <BEP20_wallet> - Request withdrawal\n"
        "/help - Show commands"
    )

    if is_admin:
        help_text += (
            "\n\n👑 Admin Commands:\n"
            "/confirm <user_id> - Confirm payment\n"
            "/processwithdraw <user_id> - Complete withdrawal"
        )

    await update.message.reply_text(help_text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help.")

# -----------------------
# Main (Render Ready)
# -----------------------
def main():
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
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", processwithdraw))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Scheduler: daily pairing reset
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_pairing_if_needed,
        CronTrigger(hour=0, minute=0),
        id="daily_reset",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("🚀 Bot running with daily reset scheduler.")
    app.run_polling()

if __name__ == "__main__":
    main()
