# -----------------------
# TXID or Screenshot Submission
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

    # Case 1: TXID submitted as text argument
    if context.args and len(context.args) == 1:
        txid = context.args[0]
        user["txid"] = txid
        save_data()

        # Notify admin
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"💳 New TXID payment submitted!\n"
                    f"User ID: {user_id}\n"
                    f"TXID: {txid}"
                )
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        await update.message.reply_text(
            "✅ TXID submitted successfully. Admin will verify your payment soon."
        )
        return

    # Case 2: Screenshot (photo) submission
    if update.message.photo:
        photo = update.message.photo[-1]  # highest resolution
        file_id = photo.file_id
        user["proof_screenshot"] = file_id
        save_data()

        # Forward screenshot to admin
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=f"🖼 Payment proof (screenshot) from user {user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send screenshot to admin: {e}")

        await update.message.reply_text(
            "✅ Screenshot received! Admin will verify your payment soon."
        )
        return

    # If no argument or photo provided
    await update.message.reply_text(
        "Please send your payment proof in one of the following ways:\n"
        "1️⃣ `/pay <transaction_id>` — if you have a TXID\n"
        "2️⃣ Send a **screenshot** of your payment directly to this chat",
        parse_mode="Markdown"
    )


# -----------------------
# Admin confirms payment (TXID or Screenshot)
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
    screenshot = user.get("proof_screenshot")

    # Check that at least one proof was submitted
    if not txid and not screenshot:
        await update.message.reply_text("❌ This user has not submitted any TXID or screenshot proof.")
        return

    # Mark user as paid
    user["paid"] = True
    save_data()

    # Give referrer bonuses
    ref_id = user.get("referrer")
    if ref_id:
        users[ref_id]["balance"] += DIRECT_BONUS
        users[ref_id]["earned_from_referrals"] += DIRECT_BONUS

        # Pairing bonus logic
        if users[ref_id]["left"] <= users[ref_id]["right"]:
            side = "left"
        else:
            side = "right"

        if users[ref_id][side] < MAX_PAIRS_PER_DAY:
            users[ref_id][side] += 1
            users[ref_id]["balance"] += PAIRING_BONUS
            users[ref_id]["earned_from_referrals"] += PAIRING_BONUS

    save_data()

    # Notify admin of confirmation summary
    summary = (
        f"✅ User {target_user_id} confirmed as paid.\n\n"
        f"🧾 Payment Details:\n"
    )
    if txid:
        summary += f"• TXID: `{txid}`\n"
    if screenshot:
        summary += "• Screenshot: Submitted ✅\n"
    summary += (
        f"\n💸 Bonuses credited to referrer (if any).\n\n"
        f"🔗 Premium Channel:\n{PREMIUM_GROUP}"
    )

    await update.message.reply_text(summary, parse_mode="Markdown")

    # Notify the user of confirmation
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=(
                f"🎉 Your payment has been confirmed!\n\n"
                f"Welcome to Premium Membership 🚀\n\n"
                f"Join the signals group:\n{PREMIUM_GROUP}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify confirmed user: {e}")

