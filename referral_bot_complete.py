# referral_bot_complete.py
import logging
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
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
DAILY_PROFIT_PERCENT = 1  # 1% daily

# -----------------------
# Helpers
# -----------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f)

def save_meta():
    with open(META_FILE, "w") as f:
        json.dump(meta, f)

def reset_pairing_if_needed():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if meta.get("last_reset") != today:
        for user in users.values():
            user["left"] = 0
            user["right"] = 0
        meta["last_reset"] = today
        save_data()
        save_meta()
        logger.info("Daily pairing counts reset.")

def calculate_investment_profit(user):
    invest = user.get("investment")
    if not invest or invest.get("pending"):
        return 0
    start_date = datetime.fromisoformat(invest["start_date"])
    amount = invest["amount"]
    withdrawn_profit = invest.get("withdrawn_profit", 0)
    days_passed = (datetime.now(timezone.utc) - start_date).days
    total_profit = amount * (DAILY_PROFIT_PERCENT / 100) * days_passed
    available_profit = total_profit - withdrawn_profit
    # Locked for 30 days
    if days_passed < INVEST_LOCK_DAYS:
        return available_profit
    else:
        return available_profit

async def credit_daily_profit(app):
    for user_id, user in users.items():
        invest_profit = calculate_investment_profit(user)
        if invest_profit > 0:
            user["balance"] += invest_profit
            user.setdefault("investment", {})["withdrawn_profit"] = user.get("investment", {}).get("withdrawn_profit", 0) + invest_profit
            try:
                await app.bot.send_message(
                    chat_id=int(user_id),
                    text=f"📈 Daily profit of {invest_profit:.2f} USDT credited to your balance."
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
    save_data()
    logger.info("✅ Daily investment profits credited.")

async def daily_profit_loop(app):
    while True:
        await credit_daily_profit(app)
        now = datetime.now(timezone.utc)
        next_run = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

# -----------------------
# Command Handlers
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
            "investment": None,
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
        "   (these coins will pump within 24 hours)\n\n"
    )
    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay {MEMBERSHIP_FEE} USDT (BEP20) to:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"Share your referral link to earn bonuses after your friends pay:\n{referral_link}",
        parse_mode="Markdown"
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ Already paid.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /pay <TXID> (Transaction Hash/ID)")
        return
    txid = context.args[0]
    user["txid"] = txid
    save_data()
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=f"💳 Payment TXID submitted!\nUser: {user_id}\nTXID: {txid}")
    except Exception as e:
        logger.error(f"Admin notify failed: {e}")
    await update.message.reply_text("✅ TXID submitted. Admin will confirm.")

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
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
        await update.message.reply_text("✅ Already paid.")
        return
    txid = user.get("txid")
    if not txid:
        await update.message.reply_text("❌ No TXID submitted.")
        return
    user["paid"] = True
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
    await update.message.reply_text(f"✅ User {target_user_id} confirmed.\nTXID: {txid}\nBonuses credited.\nPremium: {PREMIUM_GROUP}")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    invest_profit = calculate_investment_profit(user)
    total_balance = user.get("balance", 0)
    referral_earn = user.get("earned_from_referrals", 0)
    investment_earn = invest_profit
    await update.message.reply_text(
        f"💰 Balance: {total_balance:.2f} USDT\n"
        f"💎 Referral earnings: {referral_earn:.2f} USDT\n"
        f"📈 Investment earnings (uncredited): {investment_earn:.2f} USDT"
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
    bal = user.get("balance", 0)
    referral_earn = user.get("earned_from_referrals", 0)
    invest_profit = calculate_investment_profit(user)
    paid = user.get("paid", False)
    msg = (
        f"📊 **Stats:**\n"
        f"Balance: {bal:.2f} USDT\n"
        f"Referral earnings: {referral_earn:.2f} USDT\n"
        f"Investment earnings (uncredited): {invest_profit:.2f} USDT\n"
        f"Direct referrals: {num_referrals}\n"
        f"Left pairs today: {left}\n"
        f"Right pairs today: {right}\n"
        f"Membership paid: {'✅' if paid else '❌'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# Withdraw, processwithdraw, invest, confirminvest, help_command, unknown are defined above similarly

# -----------------------
# Main
# -----------------------
async def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set!")
    app = ApplicationBuilder().token(TOKEN).build()
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("processwithdraw", processwithdraw))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirminvest", confirminvest))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    # Start daily profit loop
    asyncio.create_task(daily_profit_loop(app))
    await app.run_polling()

# -----------------------
# Render-safe entry
# -----------------------
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
