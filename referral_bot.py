# referral_bot.py
import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Optional: APScheduler for auto daily ROI (install if desired)
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    APSCHEDULER_AVAILABLE = True
except Exception:
    APSCHEDULER_AVAILABLE = False

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# -----------------------
# Configuration (update if needed)
# -----------------------
DATA_FILE = "data.json"
ADMIN_ID = 6122146243  # <-- replace with your Telegram numeric ID if different
BOT_DISPLAY_NAME = "Premium Member Auto Trading Bot"

DIRECT_BONUS = 20.0
PAIRING_BONUS = 5.0
MAX_PAIRINGS_PER_DAY = 10
MIN_INVEST = 50.0
MIN_WITHDRAW = 20.0

# Your BNB Smart Chain wallet (monospaced where shown)
INVEST_WALLET = "0xC6219FFBA27247937A63963E4779e33F7930d497"
PREMIUM_GROUP = "https://t.me/+ra4eSwIYWukwMjRl"

INVESTMENT_LOCK_DAYS = 30
DAILY_ROI_PERCENT = 0.01  # 1% per day

# -----------------------
# Helpers: load/save data
# -----------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def ensure_user_structure(data, user_id, user_fullname):
    if user_id not in data:
        data[user_id] = {
            "name": user_fullname,
            "referred_by": None,
            "referrals": [],
            "total_invest": 0.0,
            "credited_for_referrer": False,

            # withdrawable: referral bonuses + accumulated ROI
            "balance": 0.0,

            # investments: list of {"amount": float, "ts": iso str}
            "investments": [],

            "pending_invest": None,
            "pending_withdrawal": None,
            "withdrawals": [],
            "daily_pairs": 0,
            "last_pair_date": None,
            "last_roi_date": None,
            "is_premium": False
        }

def is_admin(update: Update):
    return update.effective_user and update.effective_user.id == ADMIN_ID

# -----------------------
# User commands
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    ensure_user_structure(data, uid, user.full_name)

    # referral handling if provided
    if context.args:
        ref_id = context.args[0]
        if ref_id != uid and ref_id in data:
            if not data[uid]["referred_by"]:
                data[uid]["referred_by"] = ref_id
                if uid not in data[ref_id]["referrals"]:
                    data[ref_id]["referrals"].append(uid)
    save_data(data)

    referral_link = f"https://t.me/{context.bot.username}?start={uid}"
    await update.message.reply_text(
        f"👋 Welcome to *{BOT_DISPLAY_NAME}*!\n\n"
        f"Earn by investing and referring friends.\n\n"
        f"Your referral link:\n{referral_link}\n\n"
        f"Use /invest <amount> to invest (min {MIN_INVEST} USDT).\n"
        f"Check /balance and /stats for details.\n"
        f"See commands with /commands or /help.",
        parse_mode="Markdown"
    )

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    if uid not in data:
        await update.message.reply_text("Please /start first.")
        return
    referral_link = f"https://t.me/{context.bot.username}?start={uid}"
    total_refs = len(data[uid]["referrals"])
    await update.message.reply_text(f"📢 Your referral link:\n{referral_link}\n\n👥 Total referrals: {total_refs}")

async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    ensure_user_structure(data, uid, user.full_name)

    if not context.args:
        await update.message.reply_text("Usage: /invest <amount>\nExample: /invest 100")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Please enter a valid numeric amount.")
        return
    if amount < MIN_INVEST:
        await update.message.reply_text(f"Minimum investment is {MIN_INVEST} USDT.")
        return

    ts = datetime.utcnow().isoformat()
    data[uid]["pending_invest"] = {"amount": round(amount, 8), "ts": ts}
    save_data(data)

    # show wallet in monospace for clarity
    await update.message.reply_text(
        f"📈 You are about to invest *{amount} USDT* (BEP20).\n\n"
        f"Send USDT to:\n`{INVEST_WALLET}`\n\n"
        f"Then reply with the TXID or upload a screenshot here.\n"
        f"Admin will verify and approve your deposit.",
        parse_mode="Markdown"
    )

async def handle_invest_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # TXID text or screenshot for pending_invest
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    ensure_user_structure(data, uid, user.full_name)
    pending = data[uid].get("pending_invest")
    if not pending:
        return

    if update.message.text:
        proof = update.message.text
        proof_type = "TXID"
    elif update.message.photo:
        proof = update.message.photo[-1].file_id
        proof_type = "Screenshot"
    else:
        return

    data[uid]["pending_invest"]["proof"] = proof
    data[uid]["pending_invest"]["proof_type"] = proof_type
    save_data(data)

    await context.bot.send_message(
        ADMIN_ID,
        f"📥 New investment pending:\n👤 {data[uid]['name']} ({uid})\n💰 {pending['amount']} USDT\n📝 Proof: {proof_type}\n"
        f"Approve: /approve_deposit {uid} {pending['amount']}"
    )
    await update.message.reply_text("✅ Your proof has been sent to admin for verification.")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    if uid not in data:
        await update.message.reply_text("Please /start first.")
        return
    user_data = data[uid]
    invest_total = sum(inv["amount"] for inv in user_data["investments"])
    await update.message.reply_text(
        f"💵 *Your Balances:*\n\n"
        f"🏦 Investment (locked {INVESTMENT_LOCK_DAYS} days): {round(invest_total,8)} USDT\n"
        f"🎁 Withdrawable (ROI + referral): {round(user_data.get('balance',0.0),8)} USDT",
        parse_mode="Markdown"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    if uid not in data:
        await update.message.reply_text("Please /start first.")
        return
    info = data[uid]
    total_refs = len(info["referrals"])
    total_direct = total_refs * DIRECT_BONUS
    total_pairs = (sum(1 for r in info["referrals"] if data.get(r, {}).get("credited_for_referrer", False)) // 2)
    pairing_bonus_total = total_pairs * PAIRING_BONUS
    invest_total = sum(inv["amount"] for inv in info["investments"])
    premium_status = "✅ Premium Member" if info.get("is_premium") else "❌ Not Premium"

    msg = (
        f"📊 *Your Earnings Breakdown:*\n\n"
        f"🏷 Status: {premium_status}\n"
        f"🏦 Investment (locked): {round(invest_total,8)} USDT\n"
        f"🎁 Withdrawable (ROI + referral): {round(info.get('balance',0.0),8)} USDT\n\n"
        f"👥 Total Referrals: {total_refs}\n"
        f"💵 Direct Bonus (est): {round(total_direct,8)} USDT\n"
        f"💰 Pairing Bonus (est): {round(pairing_bonus_total,8)} USDT\n"
        f"💳 Total Invested (historical): {round(info.get('total_invest',0.0),8)} USDT"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def joinpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    ensure_user_structure(data, uid, user.full_name)

    if not data[uid].get("is_premium"):
        await update.message.reply_text(
            "⚠️ You need to pay the 50 USDT Premium Membership first.\n"
            "Use /invest 50 and wait for admin approval to become premium."
        )
        return

    await update.message.reply_text(
        "🌟 *Premium Members Signals Group*\n\n"
        "🔥 *Benefits:*\n"
        "🚀 You will get to know coin names before pumps\n"
        "🚀 Buy & sell targets provided\n"
        "🚀 2-5 daily signals\n"
        "🚀 Auto trading by bot\n\n"
        "🚀 1-3 special daily premium signals (expected short-term pumps).\n\n"
        f"Join here: `{PREMIUM_GROUP}`",
        parse_mode="Markdown"
    )

# -----------------------
# Withdraw (referral balance first, then unlocked investments)
# -----------------------
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    data = load_data()
    ensure_user_structure(data, uid, user.full_name)

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /withdraw <wallet_address> <amount>")
        return

    wallet = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Enter a numeric amount.")
        return

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"Minimum withdrawal is {MIN_WITHDRAW} USDT.")
        return

    user_data = data[uid]

    # compute unlocked investments
    now = datetime.utcnow()
    unlock_td = timedelta(days=INVESTMENT_LOCK_DAYS)
    unlocked_total = 0.0
    for inv in user_data.get("investments", []):
        try:
            inv_ts = datetime.fromisoformat(inv["ts"])
        except Exception:
            inv_ts = now
        if now - inv_ts >= unlock_td:
            unlocked_total += inv["amount"]

    withdrawable_total = round(user_data.get("balance", 0.0) + unlocked_total, 8)

    if amount > withdrawable_total:
        await update.message.reply_text(
            f"Insufficient withdrawable amount. Available (referral + unlocked investments): {withdrawable_total} USDT"
        )
        return

    if user_data.get("pending_withdrawal"):
        await update.message.reply_text("You already have a pending withdrawal request.")
        return

    ts = datetime.utcnow().isoformat()
    request = {
        "user_id": uid,
        "name": user_data["name"],
        "amount": round(amount, 8),
        "wallet": wallet,
        "ts": ts
    }
    user_data["pending_withdrawal"] = request
    save_data(data)

    await update.message.reply_text(
        f"✅ Withdrawal request submitted: {round(amount,8)} USDT to `{wallet}`\nWaiting for admin approval.",
        parse_mode="Markdown"
    )
    await context.bot.send_message(
        ADMIN_ID,
        f"📥 New withdrawal request\n👤 {user_data['name']} ({uid})\n💰 {round(amount,8)} USDT\n🏦 {wallet}\n"
        f"Approve: /approve {uid} {round(amount,8)}\nReject: /reject {uid}"
    )

# -----------------------
# Admin commands (hidden)
# -----------------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    await update.message.reply_text(
        "🛠️ *Admin Panel*\n\n"
        "/approve_deposit <uid> <amount> – Approve deposit\n"
        "/approve <uid> <amount> – Approve withdrawal\n"
        "/reject <uid> – Reject withdrawal\n"
        "/pending_requests – View pending withdrawals\n"
        "/dailyroi – Credit 1% ROI to all users (run once/day)\n"
        "/economy – View economy summary",
        parse_mode="Markdown"
    )

async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve_deposit <uid> <amount>")
        return
    uid = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    data = load_data()
    if uid not in data:
        await update.message.reply_text("User not found.")
        return
    pending = data[uid].get("pending_invest")
    if not pending:
        await update.message.reply_text("No pending investment.")
        return
    if round(amount, 8) != round(pending["amount"], 8):
        await update.message.reply_text("Amount does not match pending investment.")
        return

    # credit investment
    data[uid]["total_invest"] = round(data[uid].get("total_invest", 0.0) + amount, 8)
    data[uid].setdefault("investments", []).append({"amount": round(amount,8), "ts": pending.get("ts", datetime.utcnow().isoformat())})
    data[uid]["pending_invest"] = None

    # premium if amount >= MIN_INVEST (50)
    if amount >= MIN_INVEST:
        data[uid]["is_premium"] = True

    # referral bonuses to referrer
    ref_id = data[uid].get("referred_by")
    if ref_id and ref_id in data:
        ref = data[ref_id]
        ref["balance"] = round(ref.get("balance", 0.0) + DIRECT_BONUS, 8)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if ref.get("last_pair_date") != today:
            ref["daily_pairs"] = 0
            ref["last_pair_date"] = today
        credited_count = sum(1 for r in ref["referrals"] if data.get(r, {}).get("credited_for_referrer", False))
        credited_count += 1
        data[uid]["credited_for_referrer"] = True
        if (credited_count % 2 == 0) and (ref.get("daily_pairs", 0) < MAX_PAIRINGS_PER_DAY):
            ref["balance"] = round(ref["balance"] + PAIRING_BONUS, 8)
            ref["daily_pairs"] = ref.get("daily_pairs", 0) + 1
        data[ref_id] = ref

    save_data(data)
    await update.message.reply_text(f"✅ Investment approved for {data[uid]['name']} ({amount} USDT).")
    await context.bot.send_message(uid, f"🎉 Your investment of {amount} USDT has been approved and credited!")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    if len(context.args) < 2:
        return
    uid = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        return
    data = load_data()
    if uid not in data:
        return
    req = data[uid].get("pending_withdrawal")
    if not req:
        return
    if round(amount,8) != round(req["amount"],8):
        return

    remaining = amount

    # deduct referral balance first
    bal = data[uid].get("balance", 0.0)
    if bal >= remaining:
        data[uid]["balance"] = round(bal - remaining, 8)
        remaining = 0.0
    else:
        remaining = round(remaining - bal, 8)
        data[uid]["balance"] = 0.0

    # deduct unlocked investments oldest-first
    if remaining > 0:
        now = datetime.utcnow()
        unlock_td = timedelta(days=INVESTMENT_LOCK_DAYS)
        unlocked_indices = []
        for i, inv in enumerate(data[uid].get("investments", [])):
            try:
                inv_ts = datetime.fromisoformat(inv["ts"])
            except Exception:
                inv_ts = now
            if now - inv_ts >= unlock_td:
                unlocked_indices.append(i)
        # deduct
        for idx in unlocked_indices:
            if remaining <= 0:
                break
            amt = data[uid]["investments"][idx]["amount"]
            take = min(amt, remaining)
            data[uid]["investments"][idx]["amount"] = round(amt - take, 8)
            remaining = round(remaining - take, 8)
        data[uid]["investments"] = [inv for inv in data[uid]["investments"] if round(inv["amount"],8) > 0.0]

    if remaining > 0:
        await update.message.reply_text("❗ Could not fulfill withdrawal completely due to bookkeeping mismatch.")
        return

    data[uid].setdefault("withdrawals", []).append(req)
    data[uid]["pending_withdrawal"] = None
    save_data(data)
    await update.message.reply_text(f"✅ Withdrawal approved for {data[uid]['name']} ({amount} USDT).")
    await context.bot.send_message(uid, f"🎉 Your withdrawal of {amount} USDT has been approved and processed!")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    if len(context.args) < 1:
        return
    uid = context.args[0]
    data = load_data()
    if uid not in data or not data[uid].get("pending_withdrawal"):
        return
    data[uid]["pending_withdrawal"] = None
    save_data(data)
    await update.message.reply_text(f"❌ Withdrawal rejected for {data[uid]['name']}.")
    await context.bot.send_message(uid, "⚠️ Your withdrawal request was rejected by admin.")

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    data = load_data()
    requests = []
    for uid, info in data.items():
        if info.get("pending_withdrawal"):
            requests.append(info["pending_withdrawal"])
    if not requests:
        await update.message.reply_text("No pending withdrawals.")
        return
    msg = "📥 *Pending Withdrawals:*\n\n"
    for r in requests:
        msg += f"👤 {r['name']} (ID: {r['user_id']})\n💰 {r['amount']} USDT\n🏦 `{r['wallet']}`\nRequested: {r['ts']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def dailyroi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    data = load_data()
    today = datetime.utcnow().date()
    total_distributed = 0.0
    credited_count = 0
    for uid, u in data.items():
        invest_sum = sum(inv["amount"] for inv in u.get("investments", []))
        if invest_sum <= 0:
            continue
        last_roi_iso = u.get("last_roi_date")
        if last_roi_iso:
            try:
                last_roi_date = datetime.fromisoformat(last_roi_iso).date()
            except Exception:
                last_roi_date = None
            if last_roi_date == today:
                continue
        roi = round(invest_sum * DAILY_ROI_PERCENT, 8)
        if roi <= 0:
            continue
        u["balance"] = round(u.get("balance", 0.0) + roi, 8)
        u["last_roi_date"] = datetime.utcnow().isoformat()
        total_distributed += roi
        credited_count += 1
    save_data(data)
    await update.message.reply_text(
        f"✅ Daily ROI applied.\n👥 Users credited: {credited_count}\n💰 Total ROI distributed: {round(total_distributed,8)} USDT"
    )

async def economy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unknown command.")
        return
    data = load_data()
    total_users = len(data)
    total_invested = sum(sum(inv["amount"] for inv in info.get("investments", [])) for info in data.values())
    total_ref_balances = sum(info.get("balance", 0.0) for info in data.values())
    total_direct_paid = sum(1 for info in data.values() for r in info.get("referrals", []) if data.get(r, {}).get("credited_for_referrer", False)) * DIRECT_BONUS
    total_pairing_paid = sum((sum(1 for r in info.get("referrals", []) if data.get(r, {}).get("credited_for_referrer", False)) // 2) * PAIRING_BONUS for info in data.values())
    net_approx = total_invested - (total_direct_paid + total_pairing_paid + total_ref_balances)
    msg = (
        f"📊 *Economy Summary:*\n\n"
        f"👥 Total users: {total_users}\n"
        f"💰 Total invested (active): {round(total_invested,8)} USDT\n"
        f"🎁 Total direct bonuses (est): {round(total_direct_paid,8)} USDT\n"
        f"🎁 Total pairing bonuses (est): {round(total_pairing_paid,8)} USDT\n"
        f"🏦 Total referral/ROI balances (held): {round(total_ref_balances,8)} USDT\n"
        f"🔢 Net approx: {round(net_approx,8)} USDT"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Help & Commands (hide admin commands)
# -----------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = (user_id == ADMIN_ID)
    msg = (
        "💡 *Premium Member Auto Trading Bot — Command Guide*\n\n"
        "*👤 User Commands*\n"
        "/start — Register and get your referral link\n"
        "/referral — View your referral link and total referrals\n"
        "/invest <amount> — Invest (min 50 USDT)\n"
        "/balance — Check your total balance (ROI + bonuses)\n"
        "/stats — View your investment and referral breakdown\n"
        "/withdraw <wallet> <amount> — Withdraw funds (min 20 USDT)\n"
        "/pending — Check pending withdrawals\n"
        "/joinpremium — Learn about and join the Premium Group\n"
        "/commands — Quick command list\n"
    )
    if is_admin_user:
        msg += (
            "\n⚙️ *Admin Only:*\n"
            "/approve_deposit <user_id> <amount>\n"
            "/approve <user_id> <amount>\n"
            "/reject <user_id>\n"
            "/pending_requests\n"
            "/dailyroi\n"
            "/economy\n"
        )
    msg += (
        "\n💰 *Earnings*\n"
        "• 1% daily ROI credited to withdrawable balance\n"
        "• 20 USDT per referral + 5 USDT per pair\n"
        f"• Investments locked {INVESTMENT_LOCK_DAYS} days before withdrawal"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = (user_id == ADMIN_ID)
    msg = (
        "📋 *Available Commands*\n\n"
        "👤 User:\n"
        "/start\n"
        "/referral\n"
        "/invest\n"
        "/balance\n"
        "/stats\n"
        "/withdraw\n"
        "/pending\n"
        "/joinpremium\n"
        "/help\n"
    )
    if is_admin_user:
        msg += (
            "\n⚙️ Admin:\n"
            "/approve_deposit\n"
            "/approve\n"
            "/reject\n"
            "/pending_requests\n"
            "/dailyroi\n"
            "/economy\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -----------------------
# Main
# -----------------------
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        logging.error("BOT_TOKEN missing.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # user handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("invest", invest))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_invest_proof))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("joinpremium", joinpremium))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("commands", commands_list))

    # admin handlers (hidden)
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("approve_deposit", approve_deposit))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("pending_requests", pending_requests))
    app.add_handler(CommandHandler("dailyroi", dailyroi))
    app.add_handler(CommandHandler("economy", economy))

    app.post_init = lambda _: (asyncio_set_user_commands(app))

    # optional automatic daily ROI via APScheduler
    if APSCHEDULER_AVAILABLE:
        try:
            scheduler = AsyncIOScheduler()
            # run every 24 hours (adjust cron/time as needed)
            scheduler.add_job(lambda: app.create_task(_auto_dailyroi_job()), "interval", hours=24, next_run_time=datetime.utcnow())
            scheduler.start()
            logging.info("Auto daily ROI scheduler started.")
        except Exception as e:
            logging.warning(f"Scheduler failed: {e}")

    print(f"✅ {BOT_DISPLAY_NAME} running...")
    app.run_polling()

# set bot commands for users (hide admin commands)
import asyncio
async def asyncio_set_user_commands(app):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("referral", "Show your referral link"),
        BotCommand("invest", "Invest funds"),
        BotCommand("balance", "Check your balances"),
        BotCommand("stats", "Show detailed earnings"),
        BotCommand("withdraw", "Request withdrawal"),
        BotCommand("joinpremium", "Join premium group"),
        BotCommand("help", "Detailed command guide"),
        BotCommand("commands", "Quick command list")
    ]
    await app.bot.set_my_commands(commands)

# helper for scheduler (auto dailyroi)
async def _auto_dailyroi_job():
    data = load_data()
    today = datetime.utcnow().date()
    total_distributed = 0.0
    for uid, u in data.items():
        invest_sum = sum(inv["amount"] for inv in u.get("investments", []))
        if invest_sum <= 0:
            continue
        last_roi_iso = u.get("last_roi_date")
        if last_roi_iso:
            try:
                last_roi_date = datetime.fromisoformat(last_roi_iso).date()
            except Exception:
                last_roi_date = None
            if last_roi_date == today:
                continue
        roi = round(invest_sum * DAILY_ROI_PERCENT, 8)
        if roi <= 0:
            continue
        u["balance"] = round(u.get("balance", 0.0) + roi, 8)
        u["last_roi_date"] = datetime.utcnow().isoformat()
        total_distributed += roi
    save_data(data)
    logging.info(f"Auto daily ROI done: total distributed {total_distributed}")

if __name__ == "__main__":
    main()
