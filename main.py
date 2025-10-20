#!/usr/bin/env python3
# referral_bot_complete.py
"""
Telegram referral + investment bot (manual /distribute; APScheduler removed).

Features:
- Persistent inline Main Menu for users (Balance / Invest / Referral / FAQ / Withdraw / Help)
- Admin-only commands remain as slash commands (not shown to users in menus)
- Payment, invest, withdraw flows with admin confirm/reject inline buttons
- JSON storage: users.json, meta.json
- Admin ID: 8150987682 (as provided)
- BEP20 deposit address and premium group link included
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

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

# Admin ID provided by user
ADMIN_ID = int(os.getenv("ADMIN_ID", "8150987682"))
BOT_TOKEN = os.getenv("BOT_TOKEN")  # required
BNB_ADDRESS = os.getenv(
    "BNB_ADDRESS", "0xC6219FFBA27247937A63963E4779e33F7930d497"
)  # BEP20 wallet address
PREMIUM_GROUP = os.getenv("PREMIUM_GROUP", "https://t.me/+ra4eSwIYWukwMjRl")

MEMBERSHIP_FEE = 50
DIRECT_BONUS = 20  # Direct bonus in USDT
PAIRING_BONUS = 5  # Pairing bonus in USDT
MAX_PAIRS_PER_DAY = 10
MIN_WITHDRAW = 20
INVEST_MIN = 50
INVEST_LOCK_DAYS = 30
DAILY_PROFIT_RATE = 0.01  # 1% daily

# -----------------------
# Storage load (safe)
# -----------------------
def load_json_file(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        logger.exception("Failed to load %s - using default", path)
    return default


# initialize users and meta
users: Dict[str, Dict[str, Any]] = load_json_file(DATA_FILE, {})
meta: Dict[str, Any] = load_json_file(META_FILE, {"last_reset": None})

# Ensure existing users have expected fields
for u in users.values():
    u.setdefault("direct_bonus_total", 0.0)
    u.setdefault("pairing_bonus_total", 0.0)
    u.setdefault("left", 0)
    u.setdefault("right", 0)
    u.setdefault("earned_from_referrals", 0.0)
    u.setdefault("balance", 0.0)
    u.setdefault("referrals", [])
    u.setdefault("paid", False)

# -----------------------
# Helper functions
# -----------------------
def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(users, f, indent=2, default=str)
    except Exception:
        logger.exception("Failed to save users data.")


def save_meta():
    try:
        with open(META_FILE, "w") as f:
            json.dump(meta, f, indent=2, default=str)
    except Exception:
        logger.exception("Failed to save meta data.")


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


def add_referral_bonus(referrer_id_str: str, bonus_type: str = "membership"):
    """
    Give referrer either direct or pairing bonus depending on context.

    bonus_type:
      - "membership": give direct bonus only
      - "pairing": give pairing bonus only (respecting daily max and left/right)
    """
    ref = users.get(referrer_id_str)
    if not ref:
        return

    # initialize aggregator fields if missing
    ref.setdefault("direct_bonus_total", 0.0)
    ref.setdefault("pairing_bonus_total", 0.0)
    ref.setdefault("earned_from_referrals", 0.0)
    ref.setdefault("left", 0)
    ref.setdefault("right", 0)
    ref.setdefault("balance", 0.0)

    if bonus_type == "membership":
        # Direct referral bonus only
        ref["balance"] = ref.get("balance", 0.0) + DIRECT_BONUS
        ref["earned_from_referrals"] = ref.get("earned_from_referrals", 0.0) + DIRECT_BONUS
        ref["direct_bonus_total"] = ref.get("direct_bonus_total", 0.0) + DIRECT_BONUS
        logger.info("Direct bonus %s given to %s", DIRECT_BONUS, referrer_id_str)

    elif bonus_type == "pairing":
        # Pairing bonus only: alternate left/right to balance pairs
        side = "left" if ref.get("left", 0) <= ref.get("right", 0) else "right"
        if ref.get(side, 0) < MAX_PAIRS_PER_DAY:
            ref[side] = ref.get(side, 0) + 1
            ref["balance"] += PAIRING_BONUS
            ref["earned_from_referrals"] = ref.get("earned_from_referrals", 0.0) + PAIRING_BONUS
            ref["pairing_bonus_total"] = ref.get("pairing_bonus_total", 0.0) + PAIRING_BONUS
            logger.info("Pairing bonus %s given to %s on side %s", PAIRING_BONUS, referrer_id_str, side)
        else:
            logger.info("Pairing bonus skipped for %s: daily limit reached")


def distribute_daily_profit():
    """
    Add DAILY_PROFIT_RATE * invested_amount to each qualifying investor's balance.
    Returns number of investors credited.
    """
    now = datetime.utcnow()
    distributed_count = 0
    for uid, user in users.items():
        invest = user.get("investment")
        if invest and invest.get("active") and invest.get("start_date"):
            try:
                start = datetime.fromisoformat(invest["start_date"])
            except Exception:
                # legacy or invalid format — skip
                logger.warning("Invalid start_date for user %s", uid)
                continue
            locked_until = start + timedelta(days=INVEST_LOCK_DAYS)
            if now <= locked_until:
                profit = invest["amount"] * DAILY_PROFIT_RATE
                user["balance"] = user.get("balance", 0.0) + profit
                distributed_count += 1
    save_data()
    logger.info("💹 Distributed daily profit to %d investors.", distributed_count)
    return distributed_count


# -----------------------
# Menu utilities (NO admin buttons)
# -----------------------
def build_main_menu():
    """
    Returns InlineKeyboardMarkup for the main menu. No admin buttons included.
    """
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="menu:balance"),
         InlineKeyboardButton("💸 Invest", callback_data="menu:invest")],
        [InlineKeyboardButton("👥 Referrals", callback_data="menu:referral"),
         InlineKeyboardButton("💎 FAQ", callback_data="menu:faq")],
        [InlineKeyboardButton("🏦 Withdraw", callback_data="menu:withdraw"),
         InlineKeyboardButton("❓ Help", callback_data="menu:help")],
        [InlineKeyboardButton("🌟 Join Premium", callback_data="join_premium")]
    ]
    return InlineKeyboardMarkup(keyboard)


# -----------------------
# Command Handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user = update.effective_user
    user_id = str(user.id)
    # Register user if not exists
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
            "direct_bonus_total": 0.0,
            "pairing_bonus_total": 0.0,
        }
        # If start param is given (referral), set if valid
        if context.args:
            ref = context.args[0]
            if ref in users and ref != user_id:
                users[user_id]["referrer"] = ref
                users[ref].setdefault("referrals", []).append(user_id)
        save_data()

    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"
    benefits_text = (
        "💼 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝙑𝙄𝙋 𝙈𝙚𝙢𝙗𝙚𝙧𝙨𝙝𝙞𝙥\n\n"
        "👑 *Lifetime Membership Fee:*\n"
        "💰 𝟓𝟎𝟎 𝐔𝐒𝐃𝐓 (𝐃𝐢𝐬𝐜𝐨𝐮𝐧𝐭𝐞𝐝 𝐏𝐫𝐢𝐜𝐞) — 𝐎𝐧𝐥𝐲 𝟐 𝐒𝐥𝐨𝐭𝐬 𝐋𝐞𝐟𝐭!\n"
        "_🪙 Original Price: 1000 USDT (Lifetime)_\n\n"
        "_🔥 Benefits:_\n"
        "🚀 Early access to coins before they pump\n"
        "📊 Buy & Sell targets guidance\n"
        "📈 2–5 Daily Signals\n"
        "🤖 Auto Trading by Bot\n"
        "💎 Premium Channel Only:\n"
        " 🚀 1–3 Special Signals Daily (coins that pump within 24 h)\n\n"
        "💳 𝟏-𝐌𝐨𝐧𝐭𝐡 𝐏𝐫𝐞𝐦𝐢𝐮𝐦: 𝟓𝟎 𝐔𝐒𝐃𝐓\n\n"
    )
    # BNB address shown in monospace
    menu = build_main_menu()
    await update.message.reply_text(
        f"{benefits_text}"
        f"💰 To access, pay USDT (BEP20) to this address:\n"
        f"`{BNB_ADDRESS}`\n\n"
        f"After payment submit TXID type: `/pay <TXID>`\n\n"
        f"🔗 Your referral link:\n{referral_link}",
        parse_mode="Markdown",
        reply_markup=menu,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Available Commands*\n\n"
        "💬 General:\n"
        "• /start - Register & get your referral link\n"
        "• /faq - Learn how investing & referrals work\n"
        "• /help - Show this menu\n"
        "• /referral - Show your referral link\n\n"
        "💰 Account & Earnings:\n"
        "• /pay <TXID> - Submit membership payment\n"
        "• /invest <amount> <TXID> - Submit investment (min 50 USDT)\n"
        "• /balance - View your current balance & investment info\n"
        "• /stats - View referrals, earnings, and status\n"
        "• /withdraw <wallet> - Request withdrawal (min 20 USDT)\n\n"
        "💸 Referral Bonuses:\n"
        f"• Direct Bonus: {DIRECT_BONUS} USDT\n"
        f"• Pairing Bonus: {PAIRING_BONUS} USDT (per pair, max {MAX_PAIRS_PER_DAY}/day)\n"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=build_main_menu())
    else:
        await context.bot.send_message(chat_id=update.effective_user.id, text=text, parse_mode="Markdown")


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
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=build_main_menu())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"

    premium_text = (
        "💼 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝙑𝙄𝙋 𝙈𝙚𝙢𝙗𝙚𝙧𝙨𝙝𝙞𝙥\n\n"
        "👑 Lifetime Membership Fee:\n"
        "💰 𝟓𝟎𝟎 𝐔𝐒𝐃𝐓 (𝐃𝐢𝐬𝐜𝐨𝐮𝐧𝐭𝐞𝐝 𝐏𝐫𝐢𝐜𝐞) — 𝐎𝐧𝐥𝐲 𝟐 𝐒𝐥𝐨𝐭𝐬 𝐋𝐞𝐟𝐭!\n"
        "🪙 Original Price: 1000 USDT (Lifetime)\n\n"
        "🔥 Benefits:\n"
        "🚀 Early access to coins before they pump\n"
        "📊 Buy & Sell targets guidance\n"
        "📈 2–5 Daily Signals\n"
        "🤖 Auto Trading by Bot\n"
        "💎 Premium Channel Only:\n"
        " 🚀 1–3 Special Signals Daily (coins that pump within 24 h)\n\n"
        "💳 𝟏-𝐌𝐨𝐧𝐭𝐡 𝐏𝐫𝐞𝐦𝐢𝐮𝐦: 𝟓𝟎 𝐔𝐒𝐃𝐓\n\n"
        "💰 To access, pay USDT (BEP20) to this address:\n"
        "`0xC6219FFBA27247937A63963E4779e33F7930d497`\n\n"
        "After payment submit TXID type: `/pay <TXID>`\n\n"
        f"🔗 Your referral link:\n{referral_link}"
    )

    # Use the same inline keyboard layout already shown in the menu
    await query.message.edit_text(
        text=premium_text,
        parse_mode="Markdown",
        reply_markup=query.message.reply_markup  # reuse same buttons layout
    )
    
    
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    link = f"https://t.me/{context.bot.username}?start={user_id}"
    await update.message.reply_text(f"🔗 Your referral link:\n{link}", reply_markup=build_main_menu())


# -----------------------
# Payment flow (user submits)
# -----------------------
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(
            "Usage: /pay <TXID>\n\n"
            f"Send *{MEMBERSHIP_FEE} USDT* (BEP20) to:\n`{BNB_ADDRESS}`\nThen submit: `/pay <TXID>`",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )
        return
    txid = context.args[0]
    users.setdefault(user_id, {})
    users[user_id]["txid"] = txid
    save_data()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Payment", callback_data=f"confirm_pay:{user_id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject Payment", callback_data=f"reject_pay:{user_id}"
                ),
            ]
        ]
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💳 *New Membership Payment Submitted*\n\n"
                f"👤 User: {update.effective_user.full_name} (ID: {user_id})\n"
                f"🔗 TXID: `{txid}`\n"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify admin about membership payment.")

    await update.message.reply_text(
        "✅ TXID submitted. Admin will verify your payment soon.", parse_mode="Markdown", reply_markup=build_main_menu()
    )


async def confirm_payment_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin-only command: /confirm <user_id>
    """
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
    # confirm
    u["paid"] = True
    # mark membership_referrer_rewarded to avoid double-crediting via callback later
    if not u.get("membership_referrer_rewarded"):
        ref = u.get("referrer")
        if ref:
            add_referral_bonus(ref, "membership")
            u["membership_referrer_rewarded"] = True
    save_data()
    # send premium join button to user
    try:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💎 Join Premium Group", url=PREMIUM_GROUP)]]
        )
        await context.bot.send_message(
            chat_id=int(target),
            text="✅ Your membership payment has been confirmed! Welcome to premium.",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify user after membership confirm.")
    await update.message.reply_text(f"✅ User {target} marked as paid and referral bonuses processed.")


# -----------------------
# Investment submission (user)
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text(
            f"💹 Usage: /invest <amount> <TXID>\nMinimum: {INVEST_MIN} USDT\nDeposit to: `{BNB_ADDRESS}`",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
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

    users.setdefault(user_id, {})
    users[user_id]["pending_investment"] = {
        "amount": amount,
        "txid": txid,
        "submitted_at": datetime.utcnow().isoformat(),
    }
    save_data()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm Investment", callback_data=f"confirm_invest:{user_id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject Investment", callback_data=f"reject_invest:{user_id}"
                ),
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
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify admin of investment.")

    await update.message.reply_text(
        "✅ Investment submitted and is pending admin verification. You will be notified when confirmed.",
        parse_mode="Markdown",
        reply_markup=build_main_menu(),
    )


# -----------------------
# CallbackQuery handler (admin confirms/rejects for payments and investments)
# -----------------------
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Only admin allowed to press these inline action buttons
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ You are not authorized to perform this action.")
        return

    data = query.data  # e.g., "confirm_invest:12345" or "reject_pay:12345"
    if not data or ":" not in data:
        await query.edit_message_text("❌ Invalid action.")
        return

    action, user_id = data.split(":", 1)
    user = users.get(user_id)
    if not user:
        await query.edit_message_text("❌ User not found in DB.")
        return

    # --- Payment confirm/reject ---
    if action == "confirm_pay":
        txid = user.get("txid")
        # mark paid
        user["paid"] = True
        # reward referrer for membership if not yet rewarded
        if not user.get("membership_referrer_rewarded"):
            ref = user.get("referrer")
            if ref:
                add_referral_bonus(ref, "membership")
                user["membership_referrer_rewarded"] = True
        save_data()
        await query.edit_message_text(f"✅ Payment for user {user_id} confirmed (TXID: {txid}).")

        # send user premium join inline button & message
        try:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("💎 Join Premium Group", url=PREMIUM_GROUP)]]
            )
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    "✅ *Your membership payment has been confirmed!*\n\n"
                    "🎉 Welcome to the Premium Members Signals group 💎\n"
                    "Tap the button below to join."
                ),
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to notify user after payment confirm.")
        return

    if action == "reject_pay":
        txid = user.get("txid")
        # optionally keep txid, but notify user
        await query.edit_message_text(f"❌ Payment for user {user_id} rejected (TXID: {txid}).")
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"❌ Your membership payment (TXID: {txid}) was rejected by admin.\n"
                    "If you paid, please contact the admin with proof."
                ),
            )
        except Exception:
            logger.exception("Failed to notify user after payment rejection.")
        return

    # --- Investment confirm/reject ---
    if action == "confirm_invest":
        if "pending_investment" not in user or not user.get("pending_investment"):
            await query.edit_message_text("❌ No pending investment for this user.")
            return
        pending = user.pop("pending_investment")
        amount = pending["amount"]
        now_iso = datetime.utcnow().isoformat()
        lock_until_iso = (datetime.utcnow() + timedelta(days=INVEST_LOCK_DAYS)).isoformat()
        user["investment"] = {
            "amount": amount,
            "start_date": now_iso,
            "active": True,
            "lock_until": lock_until_iso,
            "referrer_rewarded_for_invest": False,
        }
        save_data()
        await query.edit_message_text(f"✅ Investment for user {user_id} confirmed (Amount: {amount} USDT).")

        # credit referrer for investment (pairing only)
        ref = user.get("referrer")
        if ref and not user["investment"].get("referrer_rewarded_for_invest"):
            add_referral_bonus(ref, "pairing")
            user["investment"]["referrer_rewarded_for_invest"] = True
            save_data()

        # notify user with premium group link and lock-end date
        try:
            lock_until_dt = datetime.fromisoformat(lock_until_iso)
            lock_until_str = lock_until_dt.strftime("%Y-%m-%d %H:%M UTC")
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("💎 Join Premium Group", url=PREMIUM_GROUP)]]
            )
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"🎉 *Your investment is confirmed!*\n\n"
                    f"💹 Amount: {amount:.2f} USDT\n"
                    f"🔒 Locked until: {lock_until_str}\n"
                    f"📈 You will earn *1% daily* added to your balance during the lock period.\n\n"
                    f"💎 Tap below to join the Premium Members Signals group:"
                ),
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to notify user after confirming investment.")
        return

    if action == "reject_invest":
        if "pending_investment" not in user:
            await query.edit_message_text("❌ No pending investment for this user.")
            return
        pending = user.pop("pending_investment")
        save_data()
        await query.edit_message_text(f"❌ Investment for user {user_id} has been rejected.")
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"❌ Your investment request of {pending['amount']:.2f} USDT was rejected by admin.\n"
                    "If you paid and believe this is an error, please contact the admin."
                ),
            )
        except Exception:
            logger.exception("Failed to notify user after rejecting investment.")
        return

    # --- Withdraw confirm/reject via inline buttons ---
    if action == "confirm_withdraw":
        if not user.get("pending_withdraw"):
            await query.edit_message_text("❌ No pending withdraw for this user.")
            return
        pending = user.pop("pending_withdraw")
        amount = pending.get("amount", user.get("balance", 0.0))
        # subtract from balance safely
        user["balance"] = max(user.get("balance", 0.0) - amount,
                0.0)
        save_data()
        await query.edit_message_text(
            f"✅ Withdrawal of {amount:.2f} USDT for user {user_id} marked as completed."
        )
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"✅ Your withdrawal of {amount:.2f} USDT has been processed successfully!",
            )
        except Exception:
            logger.exception("Failed to notify user after confirming withdrawal.")
        return

    if action == "reject_withdraw":
        if not user.get("pending_withdraw"):
            await query.edit_message_text("❌ No pending withdraw for this user.")
            return
        pending = user.pop("pending_withdraw")
        save_data()
        await query.edit_message_text(
            f"❌ Withdrawal for user {user_id} rejected (Amount: {pending['amount']:.2f} USDT)."
        )
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=(
                    f"❌ Your withdrawal request of {pending['amount']:.2f} USDT was rejected by admin.\n"
                    "If you believe this is an error, please contact support."
                ),
            )
        except Exception:
            logger.exception("Failed to notify user after withdrawal rejection.")
        return

# -----------------------
# Menu callbacks (for normal user buttons)
# -----------------------
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = query.data.split(":", 1)[1] if ":" in query.data else None
    if not data:
        await query.answer("❌ Invalid menu selection.")
        return

    await query.answer()

    user = users.get(user_id, {})
    if data == "balance":
        bal = user.get("balance", 0.0)
        inv = user.get("investment")
        inv_text = ""
        if inv and inv.get("active"):
            amt = inv.get("amount", 0.0)
            start = inv.get("start_date")
            lock_until = inv.get("lock_until")
            inv_text = (
                f"\n💹 Active Investment:\n"
                f"• Amount: {amt:.2f} USDT\n"
                f"• Started: {start}\n"
                f"• Locked until: {lock_until}"
            )
        await query.edit_message_text(
            f"💰 *Your Balance:* {bal:.2f} USDT{inv_text}",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )
    elif data == "invest":
        invest_text = (
            "💼 *Investment Instructions*\n\n"
            "💰 *Minimum Investment:* 50 USDT (BEP20)\n"
            "📈 Earn daily returns and referral rewards.\n\n"
            "💳 *Payment Address (BEP20):*\n"
            "`0xC6219FFBA27247937A63963E4779e33F7930d497`\n\n"
            "📤 *How to Invest:*\n"
            "1️⃣ Send your USDT to the address above.\n"
            "2️⃣ Submit your TXID using:\n"
            "`/invest <amount> <TXID>`\n"
            "3️⃣ Your *initial investment* will be *locked for 30 days*.\n"
            " 💹 It will generate *1% daily profit*, which will be added automatically to your balance.\n\n"
            "⏱️ Once confirmed, your balance updates automatically."
    )

         await query.edit_message_text(
             text=invest_text,
             parse_mode="Markdown",
             reply_markup=build_main_menu(),
    )

    elif data == "referral":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        refs = users.get(user_id, {}).get("referrals", [])
        await query.edit_message_text(
            f"👥 *Your Referral Link:*\n{link}\n\n👤 Total Referrals: {len(refs)}",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )

    elif data == "faq":
        text = (
            "💡 *FAQ - Auto-Trading & Investments*\n\n"
            f"• Minimum investment: *{INVEST_MIN} USDT*\n"
            f"• Deposit to BEP20 address: `{BNB_ADDRESS}`\n"
            f"• Direct bonus: *{DIRECT_BONUS} USDT*\n"
            f"• Pairing bonus: *{PAIRING_BONUS} USDT*\n"
            f"• Investment lock: *{INVEST_LOCK_DAYS} days*\n"
            f"• Daily profit: *1%* added to balance\n"
            f"• Minimum withdraw: *{MIN_WITHDRAW} USDT*\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=build_main_menu())

    elif data == "withdraw":
        await query.edit_message_text(
            f"🏦 To request withdrawal, type:\n`/withdraw <your_wallet_address>`\n\n"
            f"💵 Minimum withdrawal: *{MIN_WITHDRAW} USDT*",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )

    elif data == "help":
        await query.edit_message_text(
            "❓ *Help Menu*\n\n"
            "Use the buttons to navigate:\n"
            "💰 Balance — View your balance & investment\n"
            "💸 Invest — Submit new investment\n"
            "👥 Referral — Your referral link\n"
            "💎 FAQ — Info about bonuses and rules\n"
            "🏦 Withdraw — How to withdraw funds",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )

# -----------------------
# Withdraw command (user)
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id, {})
    if len(context.args) < 1:
        await update.message.reply_text(
            f"Usage: /withdraw <wallet_address>\nMinimum: {MIN_WITHDRAW} USDT",
            reply_markup=build_main_menu(),
        )
        return
    wallet = context.args[0]
    amount = user.get("balance", 0.0)
    if amount < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is {MIN_WITHDRAW} USDT. Your balance: {amount:.2f} USDT",
            reply_markup=build_main_menu(),
        )
        return
    user["pending_withdraw"] = {"wallet": wallet, "amount": amount, "submitted_at": datetime.utcnow().isoformat()}
    save_data()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm Withdraw", callback_data=f"confirm_withdraw:{user_id}"),
                InlineKeyboardButton("❌ Reject Withdraw", callback_data=f"reject_withdraw:{user_id}"),
            ]
        ]
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🏦 *New Withdrawal Request*\n\n"
                f"👤 User: {update.effective_user.full_name} (ID: {user_id})\n"
                f"💵 Amount: {amount:.2f} USDT\n"
                f"💳 Wallet: `{wallet}`\n"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify admin about withdraw.")

    await update.message.reply_text(
        "✅ Withdrawal request submitted. Admin will process it soon.",
        reply_markup=build_main_menu(),
    )

# -----------------------
# Admin Commands
# -----------------------
async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    count = distribute_daily_profit()
    await update.message.reply_text(f"💹 Distributed daily profit to {count} active investors.")


async def usercount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Unauthorized.")
    count = len(users)
    await update.message.reply_text(f"📊 Total registered users: {count}")


async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Unauthorized.")
    if not context.args:
        return await update.message.reply_text("Usage: /userinfo <user_id>")
    uid = context.args[0]
    user = users.get(uid)
    if not user:
        return await update.message.reply_text("❌ User not found.")
    await update.message.reply_text(json.dumps(user, indent=2))


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Unauthorized.")
    if not context.args:
        return await update.message.reply_text("Usage: /broadcast <message>")
    msg = " ".join(context.args)
    sent = 0
    for uid in list(users.keys()):
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg)
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f"📢 Broadcast sent to {sent} users.")

# -----------------------
# Main
# -----------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Basic user commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^join_premium$"))

    # Admin-only commands
    app.add_handler(CommandHandler("distribute", distribute))
    app.add_handler(CommandHandler("usercount", usercount))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("confirm", confirm_payment_manual))

    # Callback query handler (for inline buttons)
    app.add_handler(CallbackQueryHandler(callback_query_handler, pattern="^(confirm_|reject_)"))
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu:"))

    logger.info("🚀 Bot started successfully.")
    app.run_polling()


if __name__ == "__main__":
    main()
