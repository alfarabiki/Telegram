#!/usr/bin/env python3
import os
import smtplib
import asyncio
import csv
import warnings
import threading
import sys
import time
import traceback
import requests  # ✅ penting untuk SendGrid fallback
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
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"

if not TELEGRAM_TOKEN:
    raise EnvironmentError("⚠️ Missing TELEGRAM_TOKEN.")
if not EMAIL_SENDER:
    print("⚠️ EMAIL_SENDER not set.", file=sys.stderr)

# ===============================
# LOGGING
# ===============================
def log(tag, msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{tag}] {msg}")
    sys.stdout.flush()

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
def send_email_smtp(subject, body, attachments=None, max_retries=3):
    attachments = attachments or []
    status = "Gagal"

    for attempt in range(1, max_retries + 1):
        try:
            msg = MIMEMultipart()
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = EMAIL_SENDER
            msg["To"] = ", ".join(EMAIL_RECEIVERS)
            msg.attach(MIMEText(body, "plain", "utf-8"))

            for path in attachments:
                if os.path.isfile(path):
                    try:
                        part = MIMEBase("application", "octet-stream")
                        with open(path, "rb") as f:
                            part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            "Content-Disposition",
                            f"attachment; filename={os.path.basename(path)}",
                        )
                        msg.attach(part)
                    except Exception as e:
                        log("EMAIL", f"⚠️ Gagal baca attachment {path}: {e}")

            if os.getenv("RAILWAY_ENVIRONMENT"):
                raise ConnectionError("SMTP kemungkinan diblokir di Railway")

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                if SMTP_USE_TLS:
                    server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)

            log("EMAIL", f"✅ SMTP terkirim ke {msg['To']} | Subjek: {subject}")
            status = "Terkirim"
            break

        except Exception as e:
            log("EMAIL", f"Attempt {attempt}/{max_retries} gagal: {e}")
            traceback.print_exc()

            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

            # === Fallback ke SendGrid ===
            if SENDGRID_API_KEY:
                try:
                    resp = requests.post(
                        "https://api.sendgrid.com/v3/mail/send",
                        headers={
                            "Authorization": f"Bearer {SENDGRID_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "personalizations": [{"to": [{"email": EMAIL_RECEIVERS[0]}]}],
                            "from": {"email": EMAIL_SENDER},
                            "subject": subject,
                            "content": [{"type": "text/plain", "value": body}],
                        },
                        timeout=10,
                    )
                    if resp.status_code < 300:
                        log("EMAIL", f"✅ SendGrid terkirim ke {EMAIL_RECEIVERS}")
                        status = "Terkirim via SendGrid"
                    else:
                        log("EMAIL", f"SendGrid gagal: {resp.text}")
                        status = f"Gagal via SendGrid: {resp.status_code}"
                except Exception as e2:
                    log("EMAIL", f"SendGrid error: {e2}")
                    traceback.print_exc()
                    status = f"Gagal total: {e2}"

    log_csv(
        "email_log.csv", ["Waktu", "Subjek", "Status"], [datetime.now(), subject, status]
    )
    return status.startswith("Terkirim")

async def send_email(subject, body, attachments=None):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_email_smtp, subject, body, attachments)

# ===============================
# TELEGRAM + FLASK WEBHOOK
# ===============================
flask_app = Flask(__name__)
bot = Bot(token=TELEGRAM_TOKEN)
application = Application.builder().token(TELEGRAM_TOKEN).build()

PROCESSED_UPDATES = {}
PROCESSED_TTL = 120
processed_lock = threading.Lock()
per_chat_buffers = {}
buffers_lock = asyncio.Lock()

def cleanup_processed():
    now = time.time()
    with processed_lock:
        expired = [k for k, v in PROCESSED_UPDATES.items() if now - v > PROCESSED_TTL]
        for k in expired:
            del PROCESSED_UPDATES[k]

def waktu_now():
    bulan = ["Januari","Februari","Maret","April","Mei","Juni",
             "Juli","Agustus","September","Oktober","November","Desember"]
    now = datetime.now()
    return f"{now.day} {bulan[now.month-1]} {now.year} • {now.strftime('%H:%M')}"

async def flush_chat_buffer(chat_id):
    async with buffers_lock:
        buf = per_chat_buffers.get(chat_id)
        if not buf:
            return
        log("SYSTEM", f"🚀 Mulai flush buffer chat {chat_id}")

        texts = buf.get("texts", [])
        attachments = buf.get("attachments", [])
        username = buf.get("username", "-")
        first_name = buf.get("first_name", "-")

        subj = f"From Baba & Ibun – {waktu_now()} (chat {chat_id})"
        body = f"Dari: {first_name} (@{username})\n\nPesan:\n\n" + "\n\n---\n\n".join(texts or ["(kosong)"])

        success = await send_email(subj, body, attachments)

        try:
            if success:
                await bot.send_message(chat_id, "✅ Pesan & lampiran terkirim ke email.")
            else:
                await bot.send_message(chat_id, "❌ Gagal kirim email.")
        except Exception as e:
            log("TELEGRAM", f"Gagal kirim notif: {e}")

        del per_chat_buffers[chat_id]

async def buffer_watchdog():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        async with buffers_lock:
            expired = [cid for cid, buf in per_chat_buffers.items()
                       if (buf.get("created_at", now) + 70) < now]
            for cid in expired:
                log("WATCHDOG", f"⚠️ Buffer {cid} kadaluwarsa, flush manual.")
                asyncio.create_task(flush_chat_buffer(cid))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Halo! Bot aktif dan siap menerima pesan kamu!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.update_id
    with processed_lock:
        cleanup_processed()
        if uid in PROCESSED_UPDATES:
            return
        PROCESSED_UPDATES[uid] = time.time()

    user = update.message.from_user
    chat_id = update.effective_chat.id
    text = update.message.text or update.message.caption or "(tidak ada teks)"
    attachments = []
    os.makedirs("downloads", exist_ok=True)

    try:
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            path = f"downloads/{file.file_id}.jpg"
            await file.download_to_drive(path)
            attachments.append(path)
        if update.message.document:
            file = await update.message.document.get_file()
            path = f"downloads/{update.message.document.file_name}"
            await file.download_to_drive(path)
            attachments.append(path)
    except Exception as e:
        log("TELEGRAM", f"Gagal download attachment: {e}")

    await update.message.reply_text("📥 Pesan diterima. Akan dikirim dalam 1 menit.")

    async with buffers_lock:
        buf = per_chat_buffers.get(chat_id)
        if not buf:
            per_chat_buffers[chat_id] = {
                "texts": [text],
                "attachments": attachments.copy(),
                "username": user.username or "-",
                "first_name": user.first_name or "-",
                "timer_handle": None,
                "created_at": time.time(),
            }
            buf = per_chat_buffers[chat_id]
        else:
            buf["texts"].append(text)
            buf["attachments"].extend(attachments)
            buf["created_at"] = time.time()

        if buf.get("timer_handle"):
            buf["timer_handle"].cancel()

        loop = asyncio.get_running_loop()
        buf["timer_handle"] = loop.call_later(
            60, lambda cid=chat_id: asyncio.create_task(flush_chat_buffer(cid))
        )

# ===============================
# FLASK WEBHOOK
# ===============================
GLOBAL_LOOP = None

@flask_app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    log("SYSTEM", "📩 Webhook hit! Ada update masuk.")
    try:
        update_json = request.get_json(force=True)
        update = Update.de_json(update_json, bot)
        update_id = update.update_id

        with processed_lock:
            if update_id in PROCESSED_UPDATES:
                return "duplicate", 200
            PROCESSED_UPDATES[update_id] = time.time()

        if GLOBAL_LOOP is None or not GLOBAL_LOOP.is_running():
            time.sleep(1)

        fut = asyncio.run_coroutine_threadsafe(application.process_update(update), GLOBAL_LOOP)
        log("SYSTEM", f"✅ Update {update_id} dikirim ke event loop.")
        return "ok", 200

    except Exception as e:
        log("SYSTEM", f"❌ Webhook error: {e}")
        traceback.print_exc()
        return str(e), 500

# ===============================
# MAIN
# ===============================
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def init_app():
    await application.initialize()
    await application.start()
    await bot.delete_webhook(drop_pending_updates=True)
    if DOMAIN:
        url = f"https://{DOMAIN}/{TELEGRAM_TOKEN}"
        await bot.set_webhook(url=url)
        log("SYSTEM", f"✅ Webhook set: {url}")
    asyncio.create_task(buffer_watchdog())

def main():
    global GLOBAL_LOOP
    GLOBAL_LOOP = asyncio.new_event_loop()

    t = threading.Thread(target=start_background_loop, args=(GLOBAL_LOOP,), daemon=True)
    t.start()

    for i in range(20):
        if GLOBAL_LOOP.is_running():
            break
        time.sleep(0.5)

    try:
        fut = asyncio.run_coroutine_threadsafe(init_app(), GLOBAL_LOOP)
        fut.result(timeout=30)
        log("SYSTEM", "✅ Telegram app initialized dan webhook sudah diset.")
    except Exception as e:
        log("SYSTEM", f"❌ Init gagal: {e}")

    port = int(os.environ.get("PORT", 8080))
    log("SYSTEM", f"🚀 Flask listening di port {port}")
    log("BOT", "🤖 BOT RUNNING — siap menerima pesan dan webhook!")
    flask_app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    main()
