import os
import logging
from uuid import uuid4
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ===== CONFIG =====
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== DATABASES =====
users_db = {}       # {user_id: {"inbox_token": str, "name": str}}
messages_db = {}    # {message_id: {"from": int, "to": int, "type": str}}
reply_links = {}    # {user_id: target_id}

# ===== KEEP-ALIVE =====
def run_flask():
    app = Flask(__name__)
    @app.route('/')
    def home(): return "🟢 Bot Online"
    app.run(host='0.0.0.0', port=8080)

# ===== COMMAND: /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Register user if not exists
    if user.id not in users_db:
        users_db[user.id] = {
            "inbox_token": str(uuid4()),
            "name": user.full_name
        }

    # Someone clicked inbox link (start=token)
    if context.args:
        token = context.args[0]
        recipient_id = next((uid for uid, info in users_db.items() if info["inbox_token"] == token), None)

        if recipient_id:
            if recipient_id == user.id:
                await update.message.reply_text(
                    "ℹ️ This is *your own* inbox link. Share it to receive anonymous messages.",
                    parse_mode="Markdown"
                )
            else:
                context.user_data["target_id"] = recipient_id
                await update.message.reply_text(
                    "💬 Type your message below to send it!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])
                )
            return

    # Default: show inbox link
    inbox_link = f"https://t.me/{context.bot.username}?start={users_db[user.id]['inbox_token']}"
    await update.message.reply_text(
        f"🔐 *Your Anonymous Inbox*\n\n"
        f"Share this link to receive messages:\n`{inbox_link}`\n\n"
        "⚠️ All messages will be *fully anonymous*",
        parse_mode="MarkdownV2"
    )

# ===== HANDLE ANONYMOUS MESSAGES =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    # Check if replying using button
    target_id = context.user_data.get("target_id") or reply_links.get(user.id)

    if not target_id:
        await update.message.reply_text("❗ Please use someone's inbox link or a reply button to start an anonymous conversation.")
        return

    await forward_message(context, user.id, target_id, message)

    # Clear context for one-time messages
    context.user_data.pop("target_id", None)
    reply_links.pop(user.id, None)

# ===== FORWARD MESSAGE TO TARGET ANONYMOUSLY =====
async def forward_message(context: ContextTypes.DEFAULT_TYPE, from_user: int, to_user: int, message: Message):
    try:
        content = message.text or message.caption or ""
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Reply Anonymously", callback_data=f"reply_{from_user}")]])

        if message.text:
            sent = await context.bot.send_message(to_user, f"📨 *Anonymous Message*\n\n{content}", reply_markup=reply_markup, parse_mode="MarkdownV2")
        elif message.photo:
            sent = await context.bot.send_photo(to_user, message.photo[-1].file_id, caption=f"📨 *Anonymous Photo*\n\n{content}", reply_markup=reply_markup, parse_mode="MarkdownV2")
        elif message.video:
            sent = await context.bot.send_video(to_user, message.video.file_id, caption=f"📨 *Anonymous Video*\n\n{content}", reply_markup=reply_markup, parse_mode="MarkdownV2")
        elif message.voice:
            sent = await context.bot.send_voice(to_user, message.voice.file_id, caption=f"📨 *Anonymous Voice*\n\n{content}", reply_markup=reply_markup, parse_mode="MarkdownV2")
        elif message.sticker:
            sent = await context.bot.send_sticker(to_user, message.sticker.file_id, reply_markup=reply_markup)
        elif message.animation:
            # Try MarkdownV2 (escape special characters)
            escaped = content.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            sent = await context.bot.send_animation(
                to_user,
                animation=message.animation.file_id,
                caption=f"📨 *Anonymous GIF*\n\n{escaped}",
                reply_markup=reply_markup,
                parse_mode="MarkdownV2"
            )
        else:
            await context.bot.send_message(from_user, "❌ Unsupported message type.")
            return

        # Store message for reply tracking
        messages_db[sent.message_id] = {"from": from_user, "to": to_user, "type": get_message_type(message)}
        await context.bot.send_message(from_user, "✅ Message sent anonymously!")

    except Exception as e:
        logger.error(f"Forward error: {e}")
        await context.bot.send_message(from_user, "❌ Failed to send. User may have blocked the bot.")

# ===== CALLBACK: REPLY BUTTON =====
async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data.startswith("reply_"):
        target_id = int(query.data.split("_")[1])
        reply_links[user.id] = target_id
        await query.message.reply_text("💬 Type your anonymous reply below:")

# ===== UTILITY =====
def get_message_type(message: Message) -> str:
    if message.text: return "text"
    elif message.photo: return "photo"
    elif message.video: return "video"
    elif message.voice: return "voice"
    elif message.sticker: return "sticker"
    return "unknown"

# ===== MAIN =====
def main():
    Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(reply_callback, pattern="^reply_"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.answer(), pattern="^cancel$"))

    logger.info("Bot started with keep-alive")
    app.run_polling()

if __name__ == '__main__':
    main()
