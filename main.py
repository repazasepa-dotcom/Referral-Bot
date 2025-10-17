import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
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
# Storage Files
# -----------------------
DATA_FILE = "users.json"
META_FILE = "meta.json"

# -----------------------
# Load Data
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
ADMIN_ID = 8150987682  # your Telegram ID
DIRECT_BONUS = 20
PAIRING_BONUS = 5
MAX_PAIRS_PER_DAY = 10
MEMBERSHIP_FEE = 50
BNB_ADDRESS = "0xC6219FFBA27247937A63963E4779e33F7930d497"
PREMIUM_GROUP = "https://t.me/+ra4eSwIYWukwMjRl"
MIN_WITHDRAW = 20
MIN_INVEST = 50
LOCK_DAYS = 30
DAILY_PROFIT_PERCENT = 1  # 1% daily

# -----------------------
# Helper Functions
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
            "investment": None
        }

        if context.args:
            ref_id = context.args[0]
            if ref_id in users and ref_id != user_id:
                users[user_id]["referrer"] = ref_id
                users[ref_id].setdefault("referrals", []).append(user_id)

    save_data()

    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"

    benefits_text = (
        "🔥 *Premium Membership Benefits* 🔥\n\n"
        "🚀 Get coin names before pump\n"
        "📈 Buy & sell guidance\n"
        "💰 2-5 daily trading signals\n"
        "🤖 Auto-trading bot access\n"
        "🎯 1–3 exclusive premium signals daily\n\n"
    )

    await update.message.reply_text(
        f"{benefits_text}"
        f"💳 To access, pay *{MEMBERSHIP_FEE} USDT* (BEP20) to:\n`{BNB_ADDRESS}`\n\n"
        f"📨 Then send `/pay <TXID>` after payment.\n\n"
        f"🎁 Your referral link:\n{referral_link}",
        parse_mode="Markdown"
    )

# -----------------------
# /pay Command
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return

    if user.get("paid"):
        await update.message.reply_text("✅ You already have premium access.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /pay <transaction_id>")
        return

    txid = context.args[0]
    user["txid"] = txid
    save_data()

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💳 *New Payment Submitted!*\nUser ID: {user_id}\nTXID: `{txid}`",
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ TXID submitted. Admin will verify your payment soon.")

# -----------------------
# /confirm Command (Admin)
# -----------------------
async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You’re not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /confirm <user_id>")
        return

    uid = context.args[0]
    user = users.get(uid)
    if not user:
        await update.message.reply_text("❌ User not found.")
        return

    user["paid"] = True
    save_data()

    ref_id = user.get("referrer")
    if ref_id:
        users[ref_id]["balance"] += DIRECT_BONUS
        users[ref_id]["earned_from_referrals"] += DIRECT_BONUS

    save_data()

    await update.message.reply_text(
        f"✅ User {uid} confirmed as paid.\n"
        f"💸 Referral bonus distributed.\n\n"
        f"🔗 Premium access: {PREMIUM_GROUP}"
    )

# -----------------------
# /invest Command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "💹 Usage: `/invest <amount> <TXID>`\n\n"
            f"💰 Minimum: {MIN_INVEST} USDT\n"
            f"📥 Send to BEP20 address:\n`{BNB_ADDRESS}`",
            parse_mode="Markdown"
        )
        return

    amount = float(context.args[0])
    if amount < MIN_INVEST:
        await update.message.reply_text(f"❌ Minimum investment is {MIN_INVEST} USDT.")
        return

    txid = context.args[1]
    user["pending_investment"] = {"amount": amount, "txid": txid}
    save_data()

    await update.message.reply_text("✅ Investment TXID submitted! Admin will verify soon.")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"💰 *New Investment Submitted!*\n"
            f"👤 User ID: {user_id}\n💵 Amount: {amount} USDT\n🔗 TXID: `{txid}`"
        ),
        parse_mode="Markdown"
    )

# -----------------------
# /confirm_invest (Admin)
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /confirm_invest <user_id>")
        return

    uid = context.args[0]
    user = users.get(uid)
    if not user or "pending_investment" not in user:
        await update.message.reply_text("❌ No pending investment for this user.")
        return

    invest = user.pop("pending_investment")
    amount = invest["amount"]

    user["investment"] = {
        "amount": amount,
        "start_date": datetime.utcnow().isoformat(),
        "lock_until": (datetime.utcnow() + timedelta(days=LOCK_DAYS)).isoformat(),
        "active": True,
    }
    save_data()

    await update.message.reply_text(f"✅ Investment confirmed for user {uid}.")
    await context.bot.send_message(
        chat_id=int(uid),
        text=(
            f"🎉 Your investment of {amount} USDT has been confirmed!\n"
            f"🔒 Locked for {LOCK_DAYS} days.\n"
            f"💰 You’ll earn 1% daily profit to your balance!"
        )
    )

# -----------------------
# /distribute (Admin)
# -----------------------
def distribute_daily_profit():
    now = datetime.utcnow()
    count = 0
    for user in users.values():
        invest = user.get("investment")
        if invest and invest["active"]:
            start = datetime.fromisoformat(invest["start_date"])
            if now >= start + timedelta(days=1):
                profit = invest["amount"] * DAILY_PROFIT_PERCENT / 100
                user["balance"] += profit
                count += 1
    save_data()
    return count

async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    count = distribute_daily_profit()
    await update.message.reply_text(f"✅ Distributed 1% profit to {count} investors!")

# -----------------------
# /balance Command
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)

    if not user:
        await update.message.reply_text("❌ You are not registered.")
        return

    bal = user.get("balance", 0)
    invest_info = user.get("investment")

    if invest_info:
        lock_until = datetime.fromisoformat(invest_info["lock_until"])
        days_left = (lock_until - datetime.utcnow()).days
        inv_text = (
            f"\n💹 Active Investment: {invest_info['amount']} USDT"
            f"\n🔒 Locked for {days_left} more days"
        )
    else:
        inv_text = "\n💹 No active investment"

    await update.message.reply_text(
        f"💰 Balance: {bal:.2f} USDT{inv_text}", parse_mode="Markdown"
    )

# -----------------------
# /stats Command
# -----------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Not registered. Use /start first.")
        return

    num_referrals = len(user.get("referrals", []))
    earned_from_referrals = user.get("earned_from_referrals", 0)
    balance_amount = user.get("balance", 0)
    paid = user.get("paid", False)

    invest_info = ""
    if user.get("investment"):
        inv = user["investment"]
        lock_until = datetime.fromisoformat(inv["lock_until"])
        days_left = (lock_until - datetime.utcnow()).days
        invest_info = (
            f"\n💹 Investment: {inv['amount']} USDT"
            f"\n🔒 Locked for {days_left} more days"
        )

    await update.message.reply_text(
        f"📊 Your Stats:\n\n"
        f"👥 Referrals: {num_referrals}\n"
        f"💎 Earned from Referrals: {earned_from_referrals:.2f} USDT\n"
        f"💰 Balance: {balance_amount:.2f} USDT\n"
        f"🏦 Membership Paid: {'✅ Yes' if paid else '❌ No'}\n"
        f"{invest_info}",
        parse_mode="Markdown"
    )

# -----------------------
# /faq Command
# -----------------------
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 *Frequently Asked Questions* 💬\n\n"
        "💹 *Auto-Trading Investment Feature*\n\n"
        "🚀 What it is:\n"
        "Invest USDT with the bot to join an *auto-trading system*.\n"
        "You earn **1% profit daily** once confirmed by admin!\n\n"
        "⚙️ *How it works:*\n"
        f"1️⃣ Minimum investment: {MIN_INVEST} USDT\n"
        f"2️⃣ Send USDT to: `{BNB_ADDRESS}` (BEP20)\n"
        "3️⃣ Submit your TXID using `/invest <amount> <txid>`\n"
        "4️⃣ Admin confirms your investment\n"
        f"5️⃣ Locked for {LOCK_DAYS} days — cannot withdraw early\n"
        "6️⃣ Earn 1% daily profit to your withdrawable balance 💸\n\n"
        "🎁 *Referral Bonuses:*\n"
        "Earn referral rewards each time your friends join or invest!\n\n"
        "💡 *Example:*\n"
        "Invest 100 USDT → Earn 1 USDT per day 💰"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# -----------------------
# /withdraw Command
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered.")
        return

    balance = user.get("balance", 0)
    if balance < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is {MIN_WITHDRAW} USDT. Your balance: {balance:.2f} USDT"
        )
        return

    if not context.args:
        await update.message.reply_text("Usage: /withdraw <BEP20_wallet>")
        return

    wallet = context.args[0]
    user["pending_withdraw"] = {"amount": balance, "wallet": wallet}
    save_data()

    await update.message.reply_text(
        f"✅ Withdrawal request received!\nAmount: {balance:.2f} USDT\nWallet: {wallet}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 New withdrawal!\nUser: {user_id}\nAmount: {balance:.2f}\nWallet: {wallet}"
    )

# -----------------------
# /processwithdraw (Admin)
# -----------------------
async def processwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
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
    amount = pending["amount"]
    user["balance"] -= amount
    save_data()

    await context.bot.send_message(
        chat_id=int(uid),
        text=f"✅ Your withdrawal of {amount:.2f} USDT has been processed!"
    )
    await update.message.reply_text(f"✅ User {uid} notified successfully.")

# -----------------------
# Run Bot
# -----------------------
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("⚠️ BOT_TOKEN not set!")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirm_invest", confirm_invest))
    app.add_handler(CommandHandler("distribute", distribute))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", processwithdraw))
    app.add_handler(MessageHandler(filters.COMMAND, lambda u, c: u.message.reply_text("❌ Unknown command!")))

    logger.info("🤖 Bot running successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()
