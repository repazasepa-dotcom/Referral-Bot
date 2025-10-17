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
# Storage
# -----------------------
DATA_FILE = "users.json"
META_FILE = "meta.json"

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
# Helper Functions
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
    if not invest or invest.get("pending") or not invest.get("start_date"):
        return 0
    try:
        start_date = datetime.fromisoformat(invest["start_date"])
    except Exception:
        return 0
    amount = invest["amount"]
    withdrawn_profit = invest.get("withdrawn_profit", 0)
    days_passed = (datetime.now(timezone.utc) - start_date).days
    total_profit = amount * (DAILY_PROFIT_PERCENT / 100) * days_passed
    return total_profit - withdrawn_profit

# -----------------------
# Daily Profit & Unlock Loop
# -----------------------
async def daily_profit_loop(app):
    while True:
        try:
            now = datetime.now(timezone.utc)
            for user_id, user in users.items():
                # Credit daily profit
                profit = calculate_investment_profit(user)
                if profit > 0:
                    user["balance"] += profit
                    user.setdefault("investment", {})["withdrawn_profit"] = user.get("investment", {}).get("withdrawn_profit", 0) + profit
                    try:
                        await app.bot.send_message(
                            chat_id=int(user_id),
                            text=f"📈 Daily profit of {profit:.2f} USDT credited to your balance."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")

                # Check 30-day lock expiry
                invest = user.get("investment")
                if invest and not invest.get("pending") and invest.get("start_date"):
                    start_date = datetime.fromisoformat(invest["start_date"])
                    if now >= start_date + timedelta(days=INVEST_LOCK_DAYS) and not invest.get("unlocked"):
                        invest["unlocked"] = True
                        try:
                            await app.bot.send_message(
                                chat_id=int(user_id),
                                text=f"🔓 Your invested principal of {invest['amount']:.2f} USDT is now unlocked and withdrawable."
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")

            save_data()
            logger.info("✅ Daily profits credited and investments checked for unlocks.")
        except Exception as e:
            logger.error(f"Daily profit loop error: {e}")

        # Wait until next UTC midnight
        now = datetime.now(timezone.utc)
        next_run = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        wait_seconds = max(0, (next_run - now).total_seconds())
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

# -----------------------
# Balance, Stats, Withdraw, Invest
# -----------------------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    investment_profit = calculate_investment_profit(user)
    await update.message.reply_text(
        f"💰 Balance: {user.get('balance', 0):.2f} USDT\n"
        f"💎 Referral earnings: {user.get('earned_from_referrals',0):.2f} USDT\n"
        f"📈 Investment profit: {investment_profit:.2f} USDT"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_pairing_if_needed()
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    invest = user.get("investment", {})
    msg = (
        f"📊 Stats:\n"
        f"Balance: {user.get('balance',0):.2f} USDT\n"
        f"Referral earnings: {user.get('earned_from_referrals',0):.2f} USDT\n"
        f"Investment profit: {calculate_investment_profit(user):.2f} USDT\n"
        f"Direct referrals: {len(user.get('referrals',[]))}\n"
        f"Left pairs: {user.get('left',0)}\n"
        f"Right pairs: {user.get('right',0)}\n"
        f"Membership paid: {'✅' if user.get('paid') else '❌'}\n"
        f"Investment locked: {invest.get('amount',0) if invest else 0} USDT\n"
        f"Investment unlocked: {'✅' if invest.get('unlocked') else '❌'}"
    )
    await update.message.reply_text(msg)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    balance_amount = user.get("balance",0)
    if balance_amount < MIN_WITHDRAW:
        await update.message.reply_text(f"Balance {balance_amount:.2f} USDT. Min withdrawal {MIN_WITHDRAW} USDT.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /withdraw <BEP20_wallet>")
        return
    wallet_address = context.args[0]
    user["pending_withdraw"] = {
        "amount": balance_amount,
        "wallet": wallet_address,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    save_data()
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=f"💰 Withdrawal request\nUser: {user_id}\nAmount: {balance_amount:.2f} USDT\nWallet: {wallet_address}")
    except Exception as e:
        logger.error(f"Admin notify failed: {e}")
    await update.message.reply_text(f"✅ Withdrawal request received: {balance_amount:.2f} USDT")

# -----------------------
# Invest & Admin Confirm
# -----------------------
async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = users.get(user_id)
    if not user:
        await update.message.reply_text("❌ Use /start first.")
        return
    if not context.args or len(context.args) !=1:
        await update.message.reply_text("Usage: /invest <amount>")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    user["investment"] = {
        "amount": amount,
        "start_date": None,
        "pending": True,
        "withdrawn_profit":0,
        "unlocked": False
    }
    save_data()
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=f"💹 Investment request\nUser: {user_id}\nAmount: {amount:.2f} USDT")
    except Exception as e:
        logger.error(f"Admin notify failed: {e}")
    await update.message.reply_text(f"✅ Investment submitted. Admin will confirm.")

async def confirminvest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args or len(context.args)!=1:
        await update.message.reply_text("Usage: /confirminvest <user_id>")
        return
    target_user_id = context.args[0]
    user = users.get(target_user_id)
    if not user or not user.get("investment") or not user["investment"].get("pending"):
        await update.message.reply_text("❌ No pending investment.")
        return
    user["investment"]["pending"] = False
    user["investment"]["start_date"] = datetime.now(timezone.utc).isoformat()
    save_data()
    await update.message.reply_text(f"✅ User {target_user_id} investment confirmed.")
    try:
        await context.bot.send_message(chat_id=int(target_user_id),
                                       text=f"💹 Your investment of {user['investment']['amount']:.2f} USDT is confirmed.")
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id}: {e}")

# -----------------------
# Help & Unknown
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id == ADMIN_ID
    text = (
        "📌 Commands:\n"
        "/start - Register & referral link\n"
        "/pay <TXID> - Submit payment\n"
        "/balance - Show balance & earnings\n"
        "/stats - Show stats\n"
        "/withdraw <wallet> - Request withdrawal\n"
        "/invest <amount> - Invest in Auto Trading Bot\n"
        "/help - Show this menu"
    )
    if is_admin:
        text += "\n\nAdmin:\n/confirm <user_id>\n/processwithdraw <user_id>\n/confirminvest <user_id>"
    await update.message.reply_text(text)

# -----------------------
# Main & Run
# -----------------------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set!")

    app = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(CommandHandler("confirminvest", confirminvest))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.COMMAND, lambda u,c: asyncio.create_task(u.message.reply_text("❌ Unknown command"))))

    # Start daily profit loop
    asyncio.create_task(daily_profit_loop(app))

    # Run bot in already running event loop (Render-friendly)
    loop = asyncio.get_event_loop()
    loop.create_task(app.run_polling())
    loop.run_forever()
