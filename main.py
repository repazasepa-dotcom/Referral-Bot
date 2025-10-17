#!/usr/bin/env python3
# referral_bot_complete.py
import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
# Config / Constants
# -----------------------
DATA_FILE = "users.json"
META_FILE = "meta.json"

# Admin ID: prefer env var, fallback to default you used earlier.
ADMIN_ID = int(os.getenv("ADMIN_ID", "8150987682"))
BOT_TOKEN = os.getenv("BOT_TOKEN")  # required
BNB_ADDRESS = os.getenv(
    "BNB_ADDRESS",
    "0xC6219FFBA27247937A63963E4779e33F7930d497"
)  # provided earlier
PREMIUM_GROUP = os.getenv("PREMIUM_GROUP", "https://t.me/+ra4eSwIYWukwMjRl")

MEMBERSHIP_FEE = 50
DIRECT_BONUS = 20
PAIRING_BONUS = 5
MAX_PAIRS_PER_DAY = 10
MIN_WITHDRAW = 20
INVEST_MIN = 50
INVEST_LOCK_DAYS = 30
DAILY_PROFIT_RATE = 0.01  # 1% daily as decimal

# -----------------------
# Storage (simple JSON)
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
# Helpers
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
    """Give referrer the direct + pairing bonuses when their referral pays membership."""
    ref = users.get(referrer_id_str)
    if not ref:
        return
    # direct bonus
    ref["balance"] = ref.get("balance", 0) + DIRECT_BONUS
    ref["earned_from_referrals"] = ref.get("earned_from_referrals", 0) + DIRECT_BONUS
    # pairing bonus
    side = "left" if ref.get("left", 0) <= ref.get("right", 0) else "right"
    if ref.get(side, 0) < MAX_PAIRS_PER_DAY:
        ref[side] = ref.get(side, 0) + 1
        ref["balance"] += PAIRING_BONUS
        ref["earned_from_referrals"] += PAIRING_BONUS

# -----------------------
# Profit distribution
# -----------------------
def distribute_daily_profit():
    """Add 1% daily profit to every confirmed, active investment that is still in lock period."""
    now = datetime.utcnow()
    distributed_count = 0
    for uid, user in users.items():
        invest = user.get("investment")
        if invest and invest.get("active") and invest.get("start_date"):
            start = datetime.fromisoformat(invest["start_date"])
            locked_until = start + timedelta(days=INVEST_LOCK_DAYS)
            # Only give profit while within lock window (as specified)
            if now <= locked_until:
                profit = invest["amount"] * DAILY_PROFIT_RATE
                user["balance"] = user.get("balance", 0) + profit
                distributed_count += 1
    save_data()
    logger.info(f"💹 Distributed daily profit to {distributed_count} investors.")
    return distributed_count

# -----------------------
# Command Handlers
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
            "pending_withdraw": None
        }
        # referral arg
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
        f"💰 To access, pay *{MEMBERSHIP_FEE} USDT* (BEP20) to:\n`{BNB_ADDRESS}`\n\n"
        f"After payment submit TXID: `/pay <TXID>`\n\n"
        f"🔗 Your referral link:\n{referral_link}",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id == ADMIN_ID
    text = (
        "🤖 *Available Commands*\n\n"
        "💬 General:\n"
        "• /start - Register & get referral link\n"
        "• /faq - Learn how investing & referrals work\n"
        "• /help - Show this menu\n\n"
        "💰 Earning & account:\n"
        "• /pay <TXID> - Submit membership payment TXID\n"
        "• /invest <amount> <TXID> - Submit investment (min 50 USDT)\n"
        "• /balance - View balance & investment lock info\n"
        "• /stats - View referrals, earnings, investment status\n"
        "• /withdraw <wallet> - Request withdrawal (min 20 USDT)\n"
    )
    if is_admin:
        text += (
            "\n--- Admin ---\n"
            "• /distribute - Distribute daily 1% profit to active investments\n"
            "Admin receives inline buttons when users submit investments to confirm/reject."
        )
    await update.message.reply_text(text, parse_mode="Markdown")

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 *FAQ - Auto-Trading & Investments*\n\n"
        f"• Minimum investment: *{INVEST_MIN} USDT*\n"
        f"• Deposit to BEP20 (USDT): `{BNB_ADDRESS}`\n"
        "• Submit TXID via `/invest <amount> <TXID>`\n"
        "• Admin will verify — investment is *pending* until they confirm.\n"
        f"• Once confirmed, investment is locked for *{INVEST_LOCK_DAYS} days* ⏳\n"
        "• You earn *1% per day* during the lock period — profits go to your withdrawable balance.\n"
        "• Referral bonuses are added to your balance as well.\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# -----------------------
# Membership payment flow
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /pay <TXID>")
        return
    txid = context.args[0]
    users.setdefault(user_id, {}).update({"txid": txid})
    save_data()
    # notify admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💳 New membership TXID submitted\nUser ID: {user_id}\nTXID: `{txid}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Failed to notify admin about payment.")
    await update.message.reply_text("✅ TXID submitted. Admin will verify your payment soon.")

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # admin-only command to confirm membership (keeps previous naming /confirm)
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /confirm <user_id>")
        return
    target = context.args[0]
    u = users.get(target)
    if not u:
        await update.message.reply_text("❌ User not found.")
        return
    if u.get("paid"):
        await update.message.reply_text("✅ User already confirmed.")
        return
    u["paid"] = True
    save_data()
    # give referral bonus if any
    ref = u.get("referrer")
    if ref:
        add_referral_bonus(ref)
        save_data()
    await update.message.reply_text(f"✅ User {target} marked as paid and referral bonuses processed.")

# -----------------------
# Investment flow (user submits)
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text(
            f"💹 Usage: /invest <amount> <TXID>\nMinimum: {INVEST_MIN} USDT\nDeposit to: `{BNB_ADDRESS}`",
            parse_mode="Markdown"
        )
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    if amount < INVEST_MIN:
        await update.message.reply_text(f"❌ Minimum investment is {INVEST_MIN} USDT.")
        return
    txid = context.args[1]

    # Record as pending_investment
    users.setdefault(user_id, {})
    users[user_id]["pending_investment"] = {
        "amount": amount,
        "txid": txid,
        "submitted_at": datetime.utcnow().isoformat()
    }
    save_data()

    # Notify admin with inline buttons
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm Investment", callback_data=f"confirm_invest:{user_id}"),
                InlineKeyboardButton("❌ Reject Investment", callback_data=f"reject_invest:{user_id}"),
            ]
        ]
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📥 *New Investment Request*\n\n"
                f"👤 User: {update.effective_user.full_name} (ID: {user_id})\n"
                f"💵 Amount: {amount} USDT\n"
                f"🔗 TXID: `{txid}`\n"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception:
        logger.exception("Failed to notify admin of investment.")

    await update.message.reply_text(
        "✅ Investment submitted and is pending admin verification. You will be notified when confirmed.",
        parse_mode="Markdown"
    )

# -----------------------
# CallbackQuery handler for admin confirm/reject
# -----------------------
async def investment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # acknowledge callback to Telegram

    # Ensure only admin may press these buttons
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ You are not authorized to perform this action.")
        return

    data = query.data  # e.g., "confirm_invest:12345" or "reject_invest:12345"
    if not data or ":" not in data:
        await query.edit_message_text("❌ Invalid action.")
        return

    action, user_id = data.split(":", 1)
    user = users.get(user_id)
    if not user or "pending_investment" not in user:
        await query.edit_message_text("❌ No pending investment found for that user.")
        return

    pending = user.pop("pending_investment")  # remove pending regardless
    save_data()

    if action == "confirm_invest":
        # Activate investment
        amount = pending["amount"]
        user["investment"] = {
            "amount": amount,
            "start_date": datetime.utcnow().isoformat(),
            "active": True,
            "lock_until": (datetime.utcnow() + timedelta(days=INVEST_LOCK_DAYS)).isoformat(),
        }
        save_data()
        # Notify admin message (edit) and notify user
        await query.edit_message_text(f"✅ Investment for user {user_id} confirmed (Amount: {amount} USDT).")
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"🎉 Your investment of {amount:.2f} USDT has been *confirmed* by admin!\n\n"
                    f"🔒 Locked for {INVEST_LOCK_DAYS} days.\n"
                    f"📈 You will earn 1% daily profit (added to your balance)."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Failed to notify user after confirm_invest.")
    elif action == "reject_invest":
        # Notify admin message (edit) and notify user
        await query.edit_message_text(f"❌ Investment for user {user_id} has been rejected.")
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"❌ Your investment request of {pending['amount']:.2f} USDT was *rejected* by admin.\n"
                    "If you believe this is an error, please contact the admin."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Failed to notify user after reject_invest.")
    else:
        await query.edit_message_text("❌ Unknown action.")

# -----------------------
# Balance & Stats
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    u = users.get(user_id)
    if not u:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return
    bal = u.get("balance", 0.0)
    invest_info = ""
    inv = u.get("investment")
    pending = u.get("pending_investment")
    if inv and inv.get("active"):
        lock_until = datetime.fromisoformat(inv["lock_until"])
        days_left = max((lock_until - datetime.utcnow()).days, 0)
        invest_info = (
            f"\n💹 Active Investment: {inv['amount']:.2f} USDT"
            f"\n🔒 Locked for {INVEST_LOCK_DAYS} days"
            f"\n🕒 Days remaining: {days_left}"
        )
    elif pending:
        invest_info = (
            f"\n💹 Pending Investment: {pending['amount']:.2f} USDT"
            f"\n⏳ Waiting for admin confirmation"
        )
    else:
        invest_info = "\n💹 No active investment."

    await update.message.reply_text(f"💰 Balance: {bal:.2f} USDT{invest_info}", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    u = users.get(user_id)
    if not u:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return
    referrals = len(u.get("referrals", []))
    earned = u.get("earned_from_referrals", 0.0)
    bal = u.get("balance", 0.0)
    paid = u.get("paid", False)

    invest_info = ""
    inv = u.get("investment")
    pending = u.get("pending_investment")
    if inv and inv.get("active"):
        lock_until = datetime.fromisoformat(inv["lock_until"])
        days_left = max((lock_until - datetime.utcnow()).days, 0)
        invest_info = (
            f"\n💹 Investment: {inv['amount']:.2f} USDT"
            f"\n🔒 Locked, {days_left} days remaining"
        )
    elif pending:
        invest_info = f"\n💹 Pending investment: {pending['amount']:.2f} USDT (awaiting admin)"
    else:
        invest_info = "\n💹 No active investment."

    await update.message.reply_text(
        f"📊 *Your Stats*\n\n"
        f"👥 Referrals: {referrals}\n"
        f"💎 Earned from referrals: {earned:.2f} USDT\n"
        f"💰 Balance: {bal:.2f} USDT\n"
        f"🏷️ Membership paid: {'✅' if paid else '❌'}\n"
        f"{invest_info}",
        parse_mode="Markdown"
    )

# -----------------------
# Withdraw flow
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    u = users.get(user_id)
    if not u:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return
    if not context.args:
        await update.message.reply_text("🏦 Usage: /withdraw <BEP20_wallet_address>")
        return
    wallet = context.args[0]
    bal = u.get("balance", 0.0)
    if bal < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW} USDT. Your balance: {bal:.2f} USDT")
        return
    u["pending_withdraw"] = {"amount": bal, "wallet": wallet, "requested_at": datetime.utcnow().isoformat()}
    save_data()
    await update.message.reply_text(f"✅ Withdrawal request submitted for {bal:.2f} USDT.\nAdmin will process it soon.")
    # notify admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New withdrawal request\nUser: {user_id}\nAmount: {bal:.2f} USDT\nWallet: {wallet}"
        )
    except Exception:
        logger.exception("Failed to notify admin of withdrawal.")

async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /processwithdraw <user_id>")
        return
    uid = context.args[0]
    u = users.get(uid)
    if not u or "pending_withdraw" not in u:
        await update.message.reply_text("❌ No pending withdrawal for this user.")
        return
    pending = u.pop("pending_withdraw")
    amount = pending["amount"]
    u["balance"] = u.get("balance", 0.0) - amount
    save_data()
    await update.message.reply_text(f"✅ Processed withdrawal for user {uid}.")
    try:
        await context.bot.send_message(chat_id=int(uid), text=f"✅ Your withdrawal of {amount:.2f} USDT was processed.")
    except Exception:
        logger.exception("Failed to notify user after processing withdraw.")

# -----------------------
# Admin manual distribute handler
# -----------------------
async def distribute_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    count = distribute_daily_profit()
    await update.message.reply_text(f"✅ Distributed daily profit to {count} investors.")

# -----------------------
# Unknown command handler
# -----------------------
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help to see available commands.")

# -----------------------
# Boot / main
# -----------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable required.")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))

    # Admin commands
    app.add_handler(CommandHandler("confirm", confirm_payment))  # confirm membership
    app.add_handler(CommandHandler("processwithdraw", process_withdraw))
    app.add_handler(CommandHandler("distribute", distribute_handler))

    # Callback queries for inline buttons (confirm/reject investments)
    app.add_handler(CallbackQueryHandler(investment_callback_handler, pattern="^(confirm_invest|reject_invest):"))

    # Unknown
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("🤖 Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
