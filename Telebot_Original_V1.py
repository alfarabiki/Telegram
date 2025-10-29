#!/usr/bin/env python3
import os
import smtplib
import asyncio
import warnings
import csv
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
import threading

# ===============================
# CONFIG
# ===============================
warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")
PRIMARY_INSTANCE = os.getenv("PRIMARY_INSTANCE", "true").lower() == "true"

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError("⚠️ Missing environment variables! Please set TELEGRAM_TOKEN, EMAIL_SENDER, and EMAIL_PASSWORD.")


# ===============================
# LOGGING
# ===============================
def log_terminal(tag, message):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{waktu}] [{tag}] {message}", flush=True)


# ===============================
# EMAIL FUNCTION
# ===============================
def send_email(subject, body_text, attachments=None):
    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    attachments = attachments or []
    for file_path in attachments:
        if os.path.isfile(file_path):
            try:
                part = MIMEBase("application", "octet-stream")
                with open(file_path, "rb") as f:
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
                msg.attach(part)
            except Exception as e:
                log_terminal("EMAIL", f"Gagal attach {file_path}: {e}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log_terminal("EMAIL", f"✅ Email terkirim ke {msg['To']} | Subjek: {subject}")
        return "Terkirim"
    except Exception as e:
        log_terminal("EMAIL", f"❌ Gagal kirim email: {e}")
        return f"Gagal: {e}"


# ===============================
# WAKTU FORMATTER
# ===============================
def waktu_format():
    bulan = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    now = datetime.now()
    return f"{now.day} {bulan[now.month-1]} {now.year} • {now.strftime('%H:%M')}"


# ===============================
# PENGIRIMAN BUFFER
# ===============================
async def flush_pending_messages(context):
    data = context.bot_data.get("pending_messages", [])
    if not data:
        return

    body = ""
    attachments = []
    for msg in data:
        body += f"\n---\nDari: {msg['from']}\nPesan:\n{msg['text']}\n"
        attachments.extend(msg["attachments"])

    context.bot_data["pending_messages"] = []
    subject = f"From Baba & Ibun – {waktu_format()}"
    status = send_email(subject, body, attachments)

    if status == "Terkirim":
        for f in attachments:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception as e:
                    log_terminal("SYSTEM", f"Gagal hapus {f}: {e}")

    log_terminal("SYSTEM", f"✅ Semua pesan terkirim ({len(attachments)} lampiran)")


# ===============================
# HANDLERS
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo 👋 Bot aktif di Render Cloud! Kirim pesan kamu ke sini ya.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or update.message.caption or "(tanpa teks)"
    attachments = []

    os.makedirs("downloads", exist_ok=True)

    # download foto
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        path = f"downloads/photo_{file.file_id}.jpg"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    # download dokumen
    if update.message.document:
        file = await update.message.document.get_file()
        path = f"downloads/{update.message.document.file_name}"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    log_terminal("TELEGRAM", f"Dari {user.first_name or 'User'}: {text}")

    context.bot_data.setdefault("pending_messages", []).append({
        "from": f"{user.first_name or 'User'} (@{user.username or '-'})",
        "text": text,
        "attachments": attachments
    })

    if "flush_task" in context.bot_data and context.bot_data["flush_task"]:
        context.bot_data["flush_task"].cancel()

    context.bot_data["flush_task"] = asyncio.create_task(asyncio.sleep(60))
    context.bot_data["flush_task"].add_done_callback(lambda _: asyncio.create_task(flush_pending_messages(context)))

    await update.message.reply_text("✅ Pesan diterima. Akan dikirim ke email setelah 1 menit tanpa pesan baru.")


async def send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Mengirim pesan tertunda...")
    await flush_pending_messages(context)
    await update.message.reply_text("✅ Semua pesan terkirim ke email!")


# ===============================
# KEEPALIVE SERVER
# ===============================
flask_app = Flask("keepalive")

@flask_app.route("/")
def home():
    return "Bot aktif dan berjalan di Render", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


# ===============================
# MAIN (Render Friendly)
# ===============================
if __name__ == "__main__":
    if not PRIMARY_INSTANCE:
        log_terminal("SYSTEM", "⏹ Secondary instance detected — tidak menjalankan bot.")
        while True:
            asyncio.sleep(3600)

    nest_asyncio.apply()
    threading.Thread(target=run_flask, daemon=True).start()

    async def main():
        bot = Bot(TELEGRAM_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        log_terminal("SYSTEM", "✅ Webhook lama dihapus. Mulai polling...")

        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler(["send", "sent"], send_now))
        app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

        await app.run_polling(close_loop=False)

    asyncio.run(main())
