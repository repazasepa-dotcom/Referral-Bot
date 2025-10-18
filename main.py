#!/usr/bin/env python3
# referral_bot_complete.py
import os
import json
import logging
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# Configuration / Constants
# -----------------------
DATA_FILE = "users.json"
META_FILE = "meta.json"

ADMIN_ID = int(os.getenv("ADMIN_ID", "8150987682"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
BNB_ADDRESS = os.getenv(
    "BNB_ADDRESS", "0xC6219FFBA27247937A63963E4779e33F7930d497"
)
PREMIUM_GROUP = os.getenv("PREMIUM_GROUP", "https://t.me/+ra4eSwIYWukwMjRl")

MEMBERSHIP_FEE = 50
DIRECT_BONUS = 20
PAIRING_BONUS = 5
MAX_PAIRS_PER_DAY = 10
MIN_WITHDRAW = 20
INVEST_MIN = 50
INVEST_LOCK_DAYS = 30
DAILY_PROFIT_RATE = 0.01  # 1% daily

# -----------------------
# Storage
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
# Helper functions
# -----------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=2)


def save_meta():
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def reset_pairing_if_needed():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if meta.get("last_reset") != today:
        for u in users.values():
            u["left"] = 0
            u["right"] = 0
        meta["last_reset"] = today
        save_data()
        save_meta()
        logger.info("🌞 Daily pairing counts reset.")


def add_referral_bonus(referrer_id_str):
    ref = users.get(referrer_id_str)
    if not ref:
        return
    ref["balance"] = ref.get("balance", 0.0) + DIRECT_BONUS
    ref["earned_from_referrals"] = ref.get("earned_from_referrals", 0.0) + DIRECT_BONUS
    side = "left" if ref.get("left", 0) <= ref.get("right", 0) else "right"
    if ref.get(side, 0) < MAX_PAIRS_PER_DAY:
        ref[side] = ref.get(side, 0) + 1
        ref["balance"] += PAIRING_BONUS
        ref["earned_from_referrals"] += PAIRING_BONUS


def distribute_daily_profit():
    now = datetime.utcnow()
    distributed_count = 0
    for uid, user in users.items():
        invest = user.get("investment")
        if invest and invest.get("active") and invest.get("start_date"):
            start = datetime.fromisoformat(invest["start_date"])
            locked_until = start + timedelta(days=INVEST_LOCK_DAYS)
            if now <= locked_until:
                profit = invest["amount"] * DAILY_PROFIT_RATE
                user["balance"] = user.get("balance", 0.0) + profit
                distributed_count += 1
    save_data()
    logger.info(f"💹 Distributed daily profit to {distributed_count} investors.")
    return distributed_count

# -----------------------
# Commands
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user = update.effective_user
    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {
            "referrer": None,
            "balance": 0.0,
            "earned_from_referrals": 0.0,
            "left": 0,
            "right": 0,
            "referrals": [],
            "paid": False,
            "txid": None,
            "pending_investment": None,
            "investment": None,
            "pending_withdraw": None,
            "membership_referrer_rewarded": False,
        }
        if context.args:
            ref = context.args[0]
            if ref in users and ref != user_id:
                users[user_id]["referrer"] = ref
                users[ref].setdefault("referrals", []).append(user_id)
        save_data()

    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"
    benefits_text = (
        "🔥 *Premium Membership Benefits* 🔥\n\n"
        "🚀 Get coin names before pump\n"
        "📈 Guidance on buy & sell targets\n"
        "💎 2–5 daily signals\n"
        "🤖 Auto trading access\n"
        "✨ Exclusive premium alerts\n\n"
    )
    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay *{MEMBERSHIP_FEE} USDT* (BEP20) to this address:\n`{BNB_ADDRESS}`\n\n"
        f"After payment, submit TXID: `/pay <TXID>`\n\n"
        f"🔗 Your referral link:\n{referral_link}",
        parse_mode="Markdown",
    )


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ Usage: /pay <TXID>")
        return
    txid = context.args[0]
    users[user_id]["txid"] = txid
    save_data()
    await update.message.reply_text("✅ Payment TXID submitted for admin review.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"💸 Payment submitted:\nUser: `{user_id}`\nTXID: `{txid}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_payment:{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_payment:{user_id}")
            ]]
        ),
    )


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /invest <amount> <TXID>")
        return
    amount = float(context.args[0])
    txid = context.args[1]
    if amount < INVEST_MIN:
        await update.message.reply_text(f"❌ Minimum investment is {INVEST_MIN} USDT.")
        return
    users[user_id]["pending_investment"] = {"amount": amount, "txid": txid}
    save_data()
    await update.message.reply_text("✅ Investment submitted for admin confirmation.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 Investment submitted:\nUser: `{user_id}`\nAmount: {amount} USDT\nTXID: `{txid}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_invest:{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_invest:{user_id}")
            ]]
        ),
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    u = users.get(user_id, {})
    invest = u.get("investment")
    lock_text = ""
    if invest and invest.get("active"):
        start = datetime.fromisoformat(invest["start_date"])
        lock_text = f"\n⏳ Locked until: {(start + timedelta(days=INVEST_LOCK_DAYS)).strftime('%Y-%m-%d')}"
    await update.message.reply_text(
        f"💰 Balance: *{u.get('balance',0):.2f} USDT*\n"
        f"📈 Earned from referrals: *{u.get('earned_from_referrals',0):.2f} USDT*{lock_text}",
        parse_mode="Markdown",
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ Usage: /withdraw <BEP20_wallet_address>")
        return
    wallet = context.args[0]
    user = users.get(user_id)
    if not user or user.get("balance", 0) < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW} USDT.")
        return
    user["pending_withdraw"] = wallet
    save_data()
    await update.message.reply_text("✅ Withdrawal request sent for admin approval.")
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🏧 Withdrawal request:\nUser: `{user_id}`\nWallet: `{wallet}`\nAmount: {user['balance']} USDT",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw:{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw:{user_id}")
            ]]
        ),
    )


async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 *FAQ - Auto-Trading & Investments*\n\n"
        f"• Minimum investment: *{INVEST_MIN} USDT*\n"
        f"• Deposit to BEP20 address: `{BNB_ADDRESS}`\n"
        f"• Direct bonus: *{DIRECT_BONUS} USDT*\n"
        f"• Pairing bonus: *{PAIRING_BONUS} USDT*\n"
        f"• Investment lock: *{INVEST_LOCK_DAYS} days*\n"
        "• Daily profit: *1%* added to balance\n"
        f"• Minimum withdraw: *{MIN_WITHDRAW} USDT*\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = distribute_daily_profit()
    await update.message.reply_text(f"✅ Distributed daily profit to {count} investors.")


# -----------------------
# Callback Handlers (Admin)
# -----------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if len(data) != 2:
        return
    action, uid = data
    user = users.get(uid)
    if not user:
        await query.edit_message_text("❌ User not found.")
        return

    if action == "confirm_payment":
        user["paid"] = True
        ref = user.get("referrer")
        if ref and not user.get("membership_referrer_rewarded"):
            add_referral_bonus(ref)
            user["membership_referrer_rewarded"] = True
        save_data()
        await query.edit_message_text(f"✅ Payment confirmed for {uid}.")
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"🎉 Payment confirmed! Welcome to Premium!\nJoin private group:\n{PREMIUM_GROUP}",
        )

    elif action == "reject_payment":
        user["txid"] = None
        save_data()
        await query.edit_message_text(f"❌ Payment rejected for {uid}.")

    elif action == "confirm_invest":
        p = user.get("pending_investment")
        if not p:
            await query.edit_message_text("⚠️ No pending investment.")
            return
        user["investment"] = {
            "amount": p["amount"],
            "txid": p["txid"],
            "start_date": datetime.utcnow().isoformat(),
            "active": True,
        }
        user["pending_investment"] = None
        ref = user.get("referrer")
        if ref:
            add_referral_bonus(ref)
        save_data()
        await query.edit_message_text(f"✅ Investment confirmed for {uid}.")
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"✅ Investment of {user['investment']['amount']} USDT confirmed! Locked {INVEST_LOCK_DAYS} days."
        )

    elif action == "reject_invest":
        user["pending_investment"] = None
        save_data()
        await query.edit_message_text(f"❌ Investment rejected for {uid}.")

    elif action == "confirm_withdraw":
        amount = user.get("balance", 0)
        wallet = user.get("pending_withdraw")
        user["balance"] = 0
        user["pending_withdraw"] = None
        save_data()
        await query.edit_message_text(f"✅ Withdrawal confirmed for {uid}.")
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"✅ Withdrawal of {amount} USDT sent to wallet `{wallet}`",
            parse_mode="Markdown",
        )

    elif action == "reject_withdraw":
        user["pending_withdraw"] = None
        save_data()
        await query.edit_message_text(f"❌ Withdrawal rejected for {uid}.")

# -----------------------
# Main
# -----------------------
def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("distribute", distribute))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()


if __name__ == "__main__":
    run_bot()
