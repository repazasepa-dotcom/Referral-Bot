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

# Investment Constants
INVEST_LOCK_DAYS = 30
DAILY_PROFIT_PERCENT = 1  # 1% daily

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

def calculate_investment_profit(user):
    invest = user.get("investment")
    if not invest:
        return 0
    start_date = datetime.fromisoformat(invest["start_date"])
    amount = invest["amount"]
    withdrawn_profit = invest.get("withdrawn_profit", 0)

    days_passed = (datetime.utcnow() - start_date).days
    total_profit = amount * (DAILY_PROFIT_PERCENT / 100) * days_passed
    available_profit = total_profit - withdrawn_profit
    return max(available_profit, 0)

async def credit_daily_profit(app):
    for user_id, user in users.items():
        invest = user.get("investment")
        if not invest:
            continue

        start_date = datetime.fromisoformat(invest["start_date"])
        withdrawn = invest.get("withdrawn_profit", 0)
        days_passed = (datetime.utcnow() - start_date).days
        total_profit = invest["amount"] * (DAILY_PROFIT_PERCENT / 100) * days_passed
        available_profit = total_profit - withdrawn

        if available_profit > 0:
            user["balance"] += available_profit
            invest["withdrawn_profit"] += available_profit

            try:
                await app.bot.send_message(
                    chat_id=int(user_id),
                    text=f"📈 Daily profit of {available_profit:.2f} USDT has been credited to your balance."
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")

    save_data()
    logger.info("✅ Daily investment profits credited to all users.")

async def daily_profit_loop(app):
    while True:
        await credit_daily_profit(app)
        now = datetime.utcnow()
        next_run = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
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
            "txid": None
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
# Pay command
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
        await update.message.reply_text(
            "Usage: /pay <TXID>\n💡 TXID = Transaction Hash / Transaction ID from your payment."
        )
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
        "✅ TXID submitted successfully. Admin will verify your payment soon.\n"
        f"💡 Note: TXID = Transaction Hash / Transaction ID from your payment."
    )

# -----------------------
# Confirm payment (admin)
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
        await update.message.reply_text("❌ User not found.")
        return
    if user.get("paid"):
        await update.message.reply_text("✅ User is already marked as paid.")
        return
    txid = user.get("txid")
    if not txid:
        await update.message.reply_text("❌ User has not submitted a TXID yet.")
        return
    user["paid"] = True
    # Credit referral bonuses
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
        f"✅ User {target_user_id} confirmed as paid.\nTXID: {txid}\nBonuses credited to referrer.\n\n"
        f"Here is your premium signals channel link:\n{PREMIUM_GROUP}"
    )

# -----------------------
# Balance command
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return
    referral_balance = user.get("balance", 0) - calculate_investment_profit(user)
    earned_from_referrals = user.get("earned_from_referrals", 0)
    invest_profit = calculate_investment_profit(user)
    total_balance = referral_balance + invest_profit
    await update.message.reply_text(
        f"💰 **Your Balance:**\n"
        f"📌 Referral earnings: {earned_from_referrals:.2f} USDT\n"
        f"📌 Investment profit: {invest_profit:.2f} USDT\n"
        f"💎 Total balance: {total_balance:.2f} USDT",
        parse_mode="Markdown"
    )

# -----------------------
# Stats command
# -----------------------
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
    referral_balance = user.get("balance", 0) - calculate_investment_profit(user)
    earned_from_referrals = user.get("earned_from_referrals", 0)
    invest_profit = calculate_investment_profit(user)
    total_balance = referral_balance + invest_profit
    paid = user.get("paid", False)
    msg = (
        f"📊 **Your Stats:**\n"
        f"💰 Total balance: {total_balance:.2f} USDT\n"
        f"📌 Referral earnings: {earned_from_referrals:.2f} USDT\n"
        f"📌 Investment earnings: {invest_profit:.2f} USDT\n"
        f"Direct referrals: {num_referrals}\n"
        f"Left pairs today: {left}\n"
        f"Right pairs today: {right}\n"
        f"Membership paid: {'✅' if paid else '❌'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Withdraw command
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return
    bal = user.get("balance", 0)
    invest_profit = calculate_investment_profit(user)
    total_balance = bal + invest_profit
    if total_balance < MIN_WITHDRAW:
        await update.message.reply_text(f"Your total balance is {total_balance:.2f} USDT. Minimum withdrawal is {MIN_WITHDRAW} USDT.")
        return
    if not context.args:
        await update.message.reply_text("Please provide your BEP20 wallet address. Usage:\n/withdraw <wallet_address>")
        return
    wallet_address = context.args[0]
    user["pending_withdraw"] = {
        "amount": total_balance,
        "wallet": wallet_address,
        "timestamp": datetime.utcnow().isoformat()
    }
    # Update withdrawn profit
    if "investment" in user and invest_profit > 0:
        user["investment"]["withdrawn_profit"] = user["investment"].get("withdrawn_profit", 0) + invest_profit
    user["balance"] = 0
    save_data()
    await update.message.reply_text(
        f"✅ Withdrawal request received!\nAmount: {total_balance:.2f} USDT\nWallet: {wallet_address}\nAdmin will verify and process it."
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 New withdrawal request!\nUser ID: {user_id}\nAmount: {total_balance:.2f} USDT\nWallet: {wallet_address}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# -----------------------
# Invest command
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ You are not registered yet. Use /start first.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(f"Usage: /invest <TXID>\nPay to same address as membership: {BNB_ADDRESS}")
        return
    txid = context.args[0]
    user["pending_invest"] = {"txid": txid, "timestamp": datetime.utcnow().isoformat()}
    save_data()
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💹 New investment request!\nUser ID: {user_id}\nTXID: {txid}"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
    await update.message.reply_text("✅ Investment submitted. Admin will confirm your investment.")

# -----------------------
# Confirm investment (admin)
# -----------------------
async def confirm_invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /confirminvest <user_id> <amount>")
        return
    target_user_id = context.args[0]
    amount = float(context.args[1])
    user = users.get(target_user_id)
    if not user or "pending_invest" not in user:
        await update.message.reply_text("❌ No pending investment for this user.")
        return
    user["investment"] = {
        "amount": amount,
        "start_date": datetime.utcnow().isoformat(),
        "withdrawn_profit": 0
    }
    user.pop("pending_invest")
    save_data()
    await update.message.reply_text(f"✅ User {target_user_id} investment confirmed: {amount} USDT.")
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=(f"✅ Your investment of {amount} USDT has been confirmed!\n"
                  f"🔒 Locked for {INVEST_LOCK_DAYS} days.\n"
                  f"💵 You earn {DAILY_PROFIT_PERCENT}% daily profit, withdrawable via /withdraw along with your referral balance.")
        )
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id}: {e}")

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
        "💹 /invest <TXID> - Submit investment payment\n"
        "❓ /help - Show this menu"
    )
    if is_admin:
        help_text += (
            "\n\n--- Admin Commands ---\n"
            "/confirm <user_id> - Confirm user payment & give premium access\n"
            "/confirminvest <user_id> <amount> - Confirm user investment\n"
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
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirminvest", confirm_invest))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Start daily profit loop
    asyncio.create_task(daily_profit_loop(app))

    app.run_polling()
