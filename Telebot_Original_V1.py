#!/usr/bin/env python3
import os
import smtplib
import asyncio
import csv
import warnings
import threading
import sys
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
from flask import Flask, request

warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

# ===============================
# CONFIG / ENV
# ===============================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")
DOMAIN = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_URL")

# Optional SMTP override
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"

# Optional API fallback (example SendGrid)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

if not TELEGRAM_TOKEN:
    raise EnvironmentError("⚠️ Missing TELEGRAM_TOKEN environment variable.")
# EMAIL is optional but we'll warn if missing (we can still operate)
if not EMAIL_SENDER or not EMAIL_PASSWORD:
    print("⚠️ EMAIL_SENDER/EMAIL_PASSWORD not set — email mungkin gagal.", file=sys.stderr)

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
# EMAIL FUNCTION (with retries)
# ===============================
def send_email_smtp(subject, body, attachments=None, max_retries=3):
    """Send email via SMTP with retries. Returns True/False."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        log("EMAIL", "Creds not set, skipping SMTP send.")
        return False

    attachments = attachments or []
    for attempt in range(1, max_retries + 1):
        try:
            msg = MIMEMultipart()
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = EMAIL_SENDER
            msg["To"] = ", ".join(EMAIL_RECEIVERS)
            msg.attach(MIMEText(body, "plain"))

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

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                if SMTP_USE_TLS:
                    server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)

            log("EMAIL", f"Terkirim ke {msg['To']} | Subject: {subject}")
            log_csv("email_log.csv", ["timestamp", "to", "subject", "status"], [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg["To"], subject, "Terkirim"
            ])
            return True
        except Exception as e:
            log("EMAIL", f"Attempt {attempt}/{max_retries} gagal: {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # exponential backoff
            else:
                log_csv("email_log.csv", ["timestamp", "to", "subject", "status"], [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ", ".join(EMAIL_RECEIVERS), subject, f"Gagal: {e}"
                ])
                return False

async def send_email(subject, body, attachments=None):
    """Wrapper to call blocking send_email_smtp in threadpool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_email_smtp, subject, body, attachments)

# ===============================
# TELEGRAM BOT + BUFFERING LOGIC
# ===============================
flask_app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
application = Application.builder().token(TELEGRAM_TOKEN).build()

# dedupe processed updates (keep small TTL)
PROCESSED_UPDATES = {}
PROCESSED_TTL = 120  # seconds
processed_lock = threading.Lock()

# per-chat buffer for bulk attachments and delayed sending
per_chat_buffers = {}
buffers_lock = asyncio.Lock()  # used inside async handlers

def cleanup_processed():
    """Clean old update_ids (periodic)."""
    now = time.time()
    with processed_lock:
        to_del = [k for k, v in PROCESSED_UPDATES.items() if now - v > PROCESSED_TTL]
        for k in to_del:
            del PROCESSED_UPDATES[k]

# helper waktu
def waktu_now():
    bulan = [
        "Januari","Februari","Maret","April","Mei","Juni",
        "Juli","Agustus","September","Oktober","November","Desember",
    ]
    now = datetime.now()
    return f"{now.day} {bulan[now.month-1]} {now.year} • {now.strftime('%H:%M')}"

# flush function - will be scheduled per chat
async def flush_chat_buffer(chat_id):
    async with buffers_lock:
        buf = per_chat_buffers.get(chat_id)
        if not buf:
            return
        texts = buf.get("texts", [])
        attachments = buf.get("attachments", [])
        username = buf.get("username", "-")
        first_name = buf.get("first_name", "-")
        # prepare body and subject
        subj = f"From Baba & Ibun – {waktu_now()} (chat {chat_id})"
        body = f"Dari: {first_name} (@{username})\n\nPesan gabungan:\n\n" + "\n\n---\n\n".join(texts or ["(kosong)"])
        # attempt to send email (blocking called in executor)
        success = await send_email(subj, body, attachments=attachments)
        # inform user on telegram
        try:
            if success:
                await bot.send_message(chat_id=chat_id, text="✅ Pesan & lampiran berhasil dikirim ke email.")
            else:
                await bot.send_message(chat_id=chat_id, text="❌ Gagal mengirim email. Cek konfigurasi SMTP atau gunakan API email.")
        except Exception as e:
            log("TELEGRAM", f"Gagal kirim konfirmasi ke chat {chat_id}: {e}")

        # log and cleanup
        log_csv("message_log.csv", ["timestamp", "chat_id", "username", "texts", "attachments"], [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            chat_id,
            username,
            " || ".join(texts),
            ", ".join(attachments),
        ])
        # remove buffer
        del per_chat_buffers[chat_id]

# handler functions
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Halo! Bot ini aktif di Railway dan siap menerima pesan kamu!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # dedupe update
    uid = update.update_id
    with processed_lock:
        cleanup_processed()
        if uid in PROCESSED_UPDATES:
            log("SYSTEM", f"Duplicate update {uid} - diabaikan.")
            return
        PROCESSED_UPDATES[uid] = time.time()

    # extract data
    user = update.message.from_user
    chat_id = update.effective_chat.id
    text = update.message.text or update.message.caption or "(tidak ada teks)"
    attachments = []
    os.makedirs("downloads", exist_ok=True)

    # save attachments (photo/document/video/audio)
    try:
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

        if update.message.video:
            file = await update.message.video.get_file()
            path = f"downloads/{file.file_id}.mp4"
            await file.download_to_drive(custom_path=path)
            attachments.append(path)

        if update.message.audio:
            file = await update.message.audio.get_file()
            path = f"downloads/{file.file_id}.ogg"
            await file.download_to_drive(custom_path=path)
            attachments.append(path)
    except Exception as e:
        log("TELEGRAM", f"Gagal download attachment: {e}")

    log("TELEGRAM", f"Dari {user.first_name} | Pesan: {text}")
    # immediate ack to user
    try:
        await update.message.reply_text("📥 Pesan diterima. Akan dikirim dalam 1 menit (bulk untuk lampiran).")
    except Exception as e:
        log("TELEGRAM", f"Gagal kirim ack: {e}")

    # append to per-chat buffer and schedule flush (reset timer)
    async with buffers_lock:
        buf = per_chat_buffers.get(chat_id)
        if not buf:
            per_chat_buffers[chat_id] = {
                "texts": [text],
                "attachments": attachments.copy(),
                "username": user.username or "-",
                "first_name": user.first_name or "-",
                "timer_handle": None,
            }
            buf = per_chat_buffers[chat_id]
        else:
            buf["texts"].append(text)
            buf["attachments"].extend(attachments)

        # cancel previous timer and create new one (delay 60s)
        if buf.get("timer_handle"):
            try:
                buf["timer_handle"].cancel()
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        # schedule flush_chat_buffer(chat_id) after 60 seconds
        handle = loop.call_later(60, lambda cid=chat_id: asyncio.create_task(flush_chat_buffer(cid)))
        buf["timer_handle"] = handle

# ===============================
# FLASK WEBHOOK (safe submit to application)
# We'll create a dedicated asyncio loop thread on startup so we can
# call `asyncio.run_coroutine_threadsafe` safely from here.
# ===============================
GLOBAL_LOOP = None

@flask_app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is running on Railway", 200

@flask_app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    # Flask's request runs in thread; just submit update to telegram application loop
    log("SYSTEM", "📩 Webhook hit! Ada update masuk.")
    update = Update.de_json(request.get_json(force=True), bot)
    try:
        # submit to telegram application for processing
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), GLOBAL_LOOP)
        # Optionally wait a short time for scheduling to ensure handler accepted
        # but do not block long - simply return quickly.
        try:
            _ = future.result(timeout=1)
        except Exception:
            # ignore timeout — handler will run in background loop
            pass
    except Exception as e:
        log("SYSTEM", f"Gagal submit update ke app loop: {e}")
        return f"error: {e}", 500
    return "ok", 200

# ===============================
# STARTUP: create background loop thread and initialize application in that loop
# ===============================
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def init_app():
    await application.initialize()
    await application.start()
    # remove webhook and server-side webhook set
    await bot.delete_webhook(drop_pending_updates=True)
    # set webhook if DOMAIN available
    webhook_url = f"https://{DOMAIN}/{TELEGRAM_TOKEN}" if DOMAIN else None
    if webhook_url:
        try:
            await bot.set_webhook(url=webhook_url)
            log("SYSTEM", f"✅ Webhook set: {webhook_url}")
        except Exception as e:
            log("SYSTEM", f"⚠️ Gagal set webhook: {e}")
    else:
        log("SYSTEM", "⚠️ DOMAIN (RAILWAY_STATIC_URL) belum diset.")

def main():
    global GLOBAL_LOOP
    # create and start background loop thread
    GLOBAL_LOOP = asyncio.new_event_loop()
    t = threading.Thread(target=start_background_loop, args=(GLOBAL_LOOP,), daemon=True)
    t.start()
    # initialize the telegram application inside that loop
    asyncio.run_coroutine_threadsafe(init_app(), GLOBAL_LOOP).result(timeout=10)

    # run flask (development server) - if you want production, use Gunicorn + Uvicorn/Gunicorn + Workers
    port = int(os.environ.get("PORT", 8080))
    log("SYSTEM", f"🚀 Flask server aktif di port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    # register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    main()
