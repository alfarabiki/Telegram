#!/usr/bin/env python3
import os
import asyncio
import smtplib
import csv
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import Conflict, TimedOut

# ===============================
# CONFIG
# ===============================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError("Missing env vars: TELEGRAM_TOKEN, EMAIL_SENDER, EMAIL_PASSWORD")

# ===============================
# UTILITIES
# ===============================
def log(tag, msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{tag}] {msg}")

def send_email(subject, body, attachments=None):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    for f in attachments or []:
        if os.path.isfile(f):
            part = MIMEBase("application", "octet-stream")
            with open(f, "rb") as file:
                part.set_payload(file.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(f)}")
            msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
    log("EMAIL", f"Sent: {subject}")

# ===============================
# BOT HANDLERS
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot aktif dan berjalan di Render.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or "(tanpa teks)"
    attachments = []

    os.makedirs("downloads", exist_ok=True)

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        path = f"downloads/{photo.file_id}.jpg"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    if update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        path = f"downloads/{doc.file_name}"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    subject = f"Pesan dari {user.first_name or 'User'} – {datetime.now():%Y-%m-%d %H:%M}"
    body = f"Nama: {user.first_name}\nUsername: @{user.username or '-'}\nPesan:\n{text}"

    try:
        send_email(subject, body, attachments)
        await update.message.reply_text("📩 Pesan dan file terkirim ke email.")
    except Exception as e:
        log("EMAIL", f"Error: {e}")
        await update.message.reply_text("❌ Gagal mengirim email.")

async def send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fitur kirim manual belum aktif di versi ini.")

# ===============================
# MAIN LOOP (RENDER SAFE)
# ===============================
async def main():
    bot = Bot(TELEGRAM_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    log("SYSTEM", "Webhook dihapus. Mulai polling...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("send", send_now))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    while True:
        try:
            await app.run_polling(close_loop=False)
        except Conflict:
            log("SYSTEM", "⚠️ Conflict terdeteksi, menunggu 10 detik lalu retry...")
            await asyncio.sleep(10)
        except TimedOut:
            log("SYSTEM", "⏱ Timeout, retrying...")
            await asyncio.sleep(5)
        except Exception as e:
            log("SYSTEM", f"Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
