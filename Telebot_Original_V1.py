#!/usr/bin/env python3
import os
import smtplib
import asyncio
import threading
import warnings
import csv
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from email.header import Header
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask
import nest_asyncio

# ===============================
# CONFIG
# ===============================
warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError("⚠️ Missing environment variables. Please set TELEGRAM_TOKEN, EMAIL_SENDER, and EMAIL_PASSWORD.")


# ===============================
# LOGGING
# ===============================
def log_terminal(tag, message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{tag}] {message}")


# ===============================
# EMAIL FUNCTION
# ===============================
def send_email(subject, body_text, attachments=None):
    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)
    msg.attach(MIMEText(body_text, "plain"))

    attachments = attachments or []
    for file_path in attachments:
        if os.path.isfile(file_path):
            part = MIMEBase("application", "octet-stream")
            with open(file_path, "rb") as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
            msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log_terminal("EMAIL", f"Terkirim ke {msg['To']} | Subject: {subject}")
        return "Terkirim"
    except Exception as e:
        log_terminal("EMAIL", f"Gagal kirim: {e}")
        return f"Gagal: {e}"


# ===============================
# UTIL
# ===============================
def get_waktu_sekarang():
    bulan_list = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    now = datetime.now()
    return f"{now.day} {bulan_list[now.month - 1]} {now.year} • {now.strftime('%H:%M')}"


# ===============================
# TELEGRAM HANDLERS
# ===============================
async def flush_pending_messages(context):
    pending = context.bot_data.get("pending_messages", [])
    if not pending:
        return

    body = ""
    attachments = []
    for msg in pending:
        body += f"\n---\nDari: {msg['from']}\nPesan:\n{msg['text']}\n"
        attachments.extend(msg["attachments"])

    context.bot_data["pending_messages"] = []
    subject = f"From Baba & Ibun – {get_waktu_sekarang()}"
    send_email(subject, body, attachments)
    log_terminal("SYSTEM", f"✅ Pesan terkirim ({len(attachments)} lampiran)")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo 👋 Bot aktif di cloud dan siap menerima pesan kamu!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or update.message.caption or "(tanpa teks)"
    attachments = []

    os.makedirs("downloads", exist_ok=True)

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        path = f"downloads/{file.file_id}.jpg"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    if update.message.document:
        file = await update.message.document.get_file()
        path = f"downloads/{update.message.document.file_name}"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    context.bot_data.setdefault("pending_messages", []).append({
        "from": f"{user.first_name or 'User'} (@{user.username or '-'})",
        "text": text,
        "attachments": attachments,
    })

    if "flush_task" in context.bot_data and context.bot_data["flush_task"]:
        context.bot_data["flush_task"].cancel()

    context.bot_data["flush_task"] = asyncio.create_task(asyncio.sleep(60))
    context.bot_data["flush_task"].add_done_callback(lambda _: asyncio.create_task(flush_pending_messages(context)))

    await update.message.reply_text("✅ Pesan diterima, akan dikirim ke email dalam 1 menit tanpa pesan baru.")


async def send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Mengirim semua pesan tertunda...")
    await flush_pending_messages(context)


# ===============================
# FLASK KEEPALIVE
# ===============================
flask_app = Flask("keepalive")

@flask_app.route("/")
def home():
    return "Bot is alive", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=run_flask, daemon=True).start()

    async def main():
        bot = Bot(TELEGRAM_TOKEN)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            log_terminal("SYSTEM", "✅ Webhook lama dihapus.")
        except Exception as e:
            log_terminal("SYSTEM", f"⚠️ Gagal hapus webhook: {e}")

        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler(["send", "sent"], send_now))
        app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

        log_terminal("SYSTEM", "🤖 Bot aktif di Render (polling mode)...")
        await app.run_polling(drop_pending_updates=True)

    asyncio.run(main())
