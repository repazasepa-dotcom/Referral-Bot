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
            "investments": [],
            "pending_investments": []
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
# Withdraw & process with locked investment protection
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return

    # Calculate total locked investment amount
    locked_total = 0
    now = datetime.utcnow()
    for inv in user.get("investments", []):
        locked_until = datetime.fromisoformat(inv["locked_until"])
        if now < locked_until:
            locked_total += inv["amount"]

    available_balance = user.get("balance", 0) - locked_total
    if available_balance < MIN_WITHDRAW:
        await update.message.reply_text(
            f"Your available balance for withdrawal is {available_balance} USDT.\n"
            f"Minimum withdrawal is {MIN_WITHDRAW} USDT."
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
        "timestamp": now.isoformat()
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

# -----------------------
# Process withdrawals by admin
# -----------------------
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
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(f"Usage: /invest <amount> (send to {INVEST_ADDRESS})")
        return

    amount = float(context.args[0])
    user["pending_investments"].append({
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat(),
        "confirmed": False
    })
    save_data()

    await update.message.reply_text(
        f"✅ Investment request of {amount} USDT received!\n"
        f"Admin will confirm after checking your deposit to {INVEST_ADDRESS}."
    )

async def pending_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return

    pending = user.get("pending_investments", [])
    msg = "\n".join([f"{inv['amount']} USDT - Pending" for inv in pending if not inv.get("confirmed", False)])
    if not msg:
        msg = "No pending investments."
    await update.message.reply_text(msg)

async def investstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered. Use /start first.")
        return

    now = datetime.utcnow()
    investments = user.get("investments", [])
    if not investments:
        await update.message.reply_text("You have no active investments.")
        return

    msg_lines = []
    for inv in investments:
        locked_until = datetime.fromisoformat(inv["locked_until"])
        remaining_days = (locked_until - now).days
        msg_lines.append(f"{inv['amount']} USDT - Locked {remaining_days} days left")

    await update.message.reply_text("\n".join(msg_lines))

async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /confirminvest <user_id>")
        return

    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or not user.get("pending_investments"):
        await update.message.reply_text("❌ No pending investment for this user.")
        return

    for inv in user["pending_investments"]:
        if not inv.get("confirmed", False):
            inv["confirmed"] = True
            inv["last_profit_date"] = datetime.utcnow().isoformat()
            inv["locked_until"] = (datetime.utcnow() + timedelta(days=INVEST_LOCK_DAYS)).isoformat()
            user["investments"].append(inv)

    user["pending_investments"] = [inv for inv in user["pending_investments"] if not inv.get("confirmed", False)]
    save_data()

    await update.message.reply_text(f"✅ Investments confirmed for user {target_user_id}.")
