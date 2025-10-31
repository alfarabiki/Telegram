#!/usr/bin/env python3
import os
import smtplib
import asyncio
import csv
import warnings
import threading
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from email.header import Header
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from flask import Flask, request

warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

# ===============================
# CONFIG
# ===============================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")
DOMAIN = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_URL")

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError(
        "⚠️ Missing environment variables. Please set TELEGRAM_TOKEN, EMAIL_SENDER, and EMAIL_PASSWORD."
    )

# ===============================
# LOGGING
# ===============================
def log(tag, msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{tag}] {msg}")

def log_csv(path, header, row):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow(row)

# ===============================
# EMAIL FUNCTION
# ===============================
def send_email(subject, body, attachments=None):
    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)
    msg.attach(MIMEText(body, "plain"))

    attachments = attachments or []
    for path in attachments:
        if os.path.isfile(path):
            part = MIMEBase("application", "octet-stream")
            with open(path, "rb") as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(path)}",
            )
            msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log("EMAIL", f"Terkirim ke {msg['To']} | Subject: {subject}")
        log_csv(
            "email_log.csv",
            ["timestamp", "to", "subject", "status"],
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                msg["To"],
                subject,
                "Terkirim",
            ],
        )
        return True
    except Exception as e:
        log("EMAIL", f"Gagal kirim: {e}")
        log_csv(
            "email_log.csv",
            ["timestamp", "to", "subject", "status"],
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                msg["To"],
                subject,
                f"Gagal: {e}",
            ],
        )
        return False

# ===============================
# TELEGRAM HANDLERS
# ===============================
def waktu_now():
    bulan = [
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    ]
    now = datetime.now()
    return f"{now.day} {bulan[now.month-1]} {now.year} • {now.strftime('%H:%M')}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Halo! Bot ini aktif di Railway dan siap menerima pesan kamu!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or update.message.caption or "(tidak ada teks)"
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

    log("TELEGRAM", f"Dari {user.first_name} | Pesan: {text}")
    log_csv(
        "message_log.csv",
        ["timestamp", "user", "username", "message"],
        [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user.first_name,
            user.username or "-",
            text,
        ],
    )

    subject = f"From Baba & Ibun – {waktu_now()}"
    body = f"Dari: {user.first_name} (@{user.username or '-'})\n\nPesan:\n{text}"

    if send_email(subject, body, attachments):
        await update.message.reply_text("✅ Pesan kamu sudah dikirim ke email.")
    else:
        await update.message.reply_text("❌ Gagal mengirim email, coba lagi nanti.")

# ===============================
# FLASK SERVER + TELEGRAM APP
# ===============================
flask_app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
application = Application.builder().token(TELEGRAM_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

@flask_app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is running on Railway", 200

@flask_app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    print("📩 Webhook hit! Ada update masuk.", file=sys.stderr)
    update = Update.de_json(request.get_json(force=True), bot)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
    except Exception as e:
        log("ERROR", f"Gagal memproses update: {e}")
        return f"error: {e}", 500
    finally:
        loop.close()

    return "ok", 200


# ===============================
# MAIN ENTRY POINT
# ===============================
async def run_bot():
    webhook_url = f"https://{DOMAIN}/{TELEGRAM_TOKEN}" if DOMAIN else None
    try:
        await application.initialize()
        await application.start()
        await bot.delete_webhook(drop_pending_updates=True)
        if webhook_url:
            await bot.set_webhook(url=webhook_url)
            log("SYSTEM", f"✅ Webhook set: {webhook_url}")
        else:
            log("SYSTEM", "⚠️ DOMAIN (RAILWAY_STATIC_URL) belum diset.")
    except Exception as e:
        log("SYSTEM", f"⚠️ Gagal set webhook: {e}")

async def main():
    await run_bot()

    port = int(os.environ.get("PORT", 8080))

    def run_flask():
        log("SYSTEM", f"🚀 Flask server aktif di port {port}")
        flask_app.run(host="0.0.0.0", port=port, debug=False)

    thread = threading.Thread(target=run_flask)
    thread.start()

if __name__ == "__main__":
    asyncio.run(main())
