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
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TimedOut, Conflict
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
# LOGGING HELPERS
# ===============================
def log_terminal(tag, message):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{waktu}] [{tag}] {message}")


def log_email_to_csv(subject, to, status):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("email_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "to", "subject", "status"])
        writer.writerow([waktu, to, subject, status])


def log_message_to_csv(user, text):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("message_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "user", "username", "message"])
        writer.writerow([
            waktu,
            user.first_name or "User",
            user.username or "-",
            text,
        ])


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
        status = "Terkirim"
        log_terminal("EMAIL", f"Terkirim ke {msg['To']} | Subject: {subject}")
    except Exception as e:
        status = f"Gagal: {e}"
        log_terminal("EMAIL", f"Gagal kirim: {e}")

    log_email_to_csv(subject, msg["To"], status)
    return status


# ===============================
# WAKTU FORMATTER
# ===============================
def get_waktu_sekarang():
    hari_list = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    bulan_list = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    now = datetime.now()
    hari = hari_list[now.weekday()]
    bulan = bulan_list[now.month - 1]
    return f"{hari}, {now.day} {bulan} {now.year} • {now.strftime('%H:%M')}"


# ===============================
# BUFFER MESSAGE
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
    status = send_email(subject, body, attachments)

    if status == "Terkirim":
        for f in attachments:
            try:
                os.remove(f)
            except Exception as e:
                log_terminal("SYSTEM", f"Gagal hapus file {f}: {e}")

    log_terminal("SYSTEM", f"✅ Pesan terkirim ({len(attachments)} lampiran)")


# ===============================
# TELEGRAM HANDLERS
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo 👋 Bot ini aktif di cloud dan siap menerima pesan kamu!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or update.message.caption or "(tidak ada teks)"
    attachments = []

    os.makedirs("downloads", exist_ok=True)

    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        path = f"downloads/photo_{photo.file_id}.jpg"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    if update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        path = f"downloads/{doc.file_name}"
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    log_terminal("TELEGRAM", f"Dari {user.first_name or 'User'} | Pesan: {text}")
    log_message_to_csv(user, text)

    context.bot_data.setdefault("pending_messages", []).append({
        "from": f"{user.first_name or 'User'} (@{user.username or '-'})",
        "text": text,
        "attachments": attachments
    })

    if "flush_task" in context.bot_data and context.bot_data["flush_task"]:
        context.bot_data["flush_task"].cancel()

    context.bot_data["flush_task"] = asyncio.create_task(asyncio.sleep(60))
    context.bot_data["flush_task"].add_done_callback(lambda _: asyncio.create_task(flush_pending_messages(context)))

    await update.message.reply_text("✅ Pesan kamu diterima dan akan dikirim ke email dalam 1 menit tanpa aktivitas baru.")


async def send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Mengirim semua pesan tertunda...")
    await flush_pending_messages(context)


# ===============================
# KEEPALIVE SERVER (FLASK)
# ===============================
flask_app = Flask("keepalive")

@flask_app.route("/")
def home():
    return "Bot is running fine.", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


# ===============================
# MAIN LOOP (RENDER FRIENDLY)
# ===============================
if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=run_flask, daemon=True).start()

    # Reset webhook sebelum polling (agar tidak conflict)
    async def reset_webhook():
        bot = Bot(TELEGRAM_TOKEN)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            log_terminal("SYSTEM", "🔄 Webhook dan sesi lama dibersihkan.")
        except Exception as e:
            log_terminal("SYSTEM", f"⚠️ Gagal reset webhook: {e}")

    asyncio.run(reset_webhook())

    while True:
        try:
            log_terminal("SYSTEM", "🤖 Bot sedang berjalan di cloud (Polling mode)...")
            app = Application.builder().token(TELEGRAM_TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("send", send_now))
            app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
        except Conflict:
            log_terminal("SYSTEM", "⚠️ Conflict terdeteksi — menunggu instance lain berhenti...")
            time.sleep(15)
        except TimedOut:
            log_terminal("SYSTEM", "⏱ Timeout, mencoba lagi...")
            time.sleep(5)
        except KeyboardInterrupt:
            log_terminal("SYSTEM", "🛑 Bot dihentikan manual.")
            break
