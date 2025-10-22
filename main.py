
import os
from dotenv import load_dotenv

load_dotenv()
import json
import logging
from uuid import uuid4
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# === CONFIG ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DATA_FILE = "users.json"

# === DATABASE ===
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        users_db = json.load(f)
else:
    users_db = {}  # {username: {"id": int, "token": str}}

messages_db = {}  # temporary {message_id: {"from": id, "to": id}}

# === KEEP-ALIVE ===
def run_flask():
    app = Flask(__name__)
    @app.route('/')
    def home(): return "🟢 Bot is alive!"
    app.run(host='0.0.0.0', port=8080)

def save_db():
    with open(DATA_FILE, "w") as f:
        json.dump(users_db, f)

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user.username:
        await update.message.reply_text("❌ You must set a Telegram @username to use this bot.")
        return

    if user.username not in users_db:
        users_db[user.username] = {
            "id": user.id,
            "token": str(uuid4())
        }
        save_db()

    # If accessed via inbox link
    if context.args:
        token = context.args[0]
        target = next((username for username, data in users_db.items() if data["token"] == token), None)

        if target:
            target_id = users_db[target]["id"]
            if target_id == user.id:
                await update.message.reply_text("ℹ️ This is *your own* inbox link. Share it to receive anonymous messages.", parse_mode="Markdown")
            else:
                context.user_data["target_id"] = target_id
                await update.message.reply_text(
                    "💬 Type your anonymous message below to send it!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])
                )
            return

    # Default: show user their own inbox link
    inbox_link = f"https://t.me/{context.bot.username}?start={users_db[user.username]['token']}"
    await update.message.reply_text(
        f"🔐 *Your Anonymous Inbox*\n\n"
        f"Share this link to receive messages:\n`{inbox_link}`\n\n"
        "⚠️ All messages are *fully anonymous*",
        parse_mode="MarkdownV2"
    )

# === MESSAGE HANDLING ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if message.reply_to_message:
        original_id = message.reply_to_message.message_id
        if original_id in messages_db:
            recipient = messages_db[original_id]["from"] if user.id == messages_db[original_id]["to"] else messages_db[original_id]["to"]
            await forward(context, user.id, recipient, message)
            return

    target_id = context.user_data.get("target_id")
    if target_id:
        await forward(context, user.id, target_id, message)
        context.user_data.pop("target_id", None)
    else:
        await update.message.reply_text("❗ Use someone’s inbox link to send an anonymous message.")

# === CALLBACK HANDLER ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        context.user_data.pop("target_id", None)
        return

    if query.data.startswith("reply_"):
        sender_id = int(query.data.split("_")[1])
        context.user_data["target_id"] = sender_id
        await query.message.reply_text("↩️ Type your anonymous reply below.")

# === FORWARD FUNCTION ===
async def forward(context, from_id, to_id, msg: Message):
    try:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Reply Anonymously", callback_data=f"reply_{from_id}")]])

        content = msg.caption or ""

        if msg.text:
            sent = await context.bot.send_message(to_id, f"📨 *Anonymous Message*\n\n{msg.text}", reply_markup=markup, parse_mode="Markdown")
        elif msg.photo:
            sent = await context.bot.send_photo(to_id, msg.photo[-1].file_id, caption=f"📨 *Anonymous Photo*\n\n{content}", reply_markup=markup, parse_mode="Markdown")
        elif msg.video:
            sent = await context.bot.send_video(to_id, msg.video.file_id, caption=f"📨 *Anonymous Video*\n\n{content}", reply_markup=markup, parse_mode="Markdown")
        elif msg.voice:
            sent = await context.bot.send_voice(to_id, msg.voice.file_id, caption=f"📨 *Anonymous Voice*\n\n{content}", reply_markup=markup, parse_mode="Markdown")
        elif msg.animation:  # GIFs
            sent = await context.bot.send_animation(to_id, msg.animation.file_id, caption=f"📨 *Anonymous GIF*\n\n{content}", reply_markup=markup, parse_mode="Markdown")
        elif msg.sticker:
            sent = await context.bot.send_sticker(to_id, msg.sticker.file_id, reply_markup=markup)
        else:
            await context.bot.send_message(from_id, "❌ Unsupported message type.")
            return

        messages_db[sent.message_id] = {"from": from_id, "to": to_id}
        await context.bot.send_message(from_id, "✅ Sent anonymously!")

    except Exception as e:
        logger.error(f"Forward failed: {e}")
        await context.bot.send_message(from_id, "❌ Failed to deliver. Maybe the user blocked the bot?")

# === MAIN ===
def main():
    # Start Flask keep-alive server
    Thread(target=run_flask, daemon=True).start()

    # Build and run Telegram bot
    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()