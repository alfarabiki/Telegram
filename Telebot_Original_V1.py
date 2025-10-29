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
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.error import TimedOut, Conflict
import nest_asyncio

# ===== SUPPRESS WARNING =====
warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

# ===== KONFIG ENV =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError("⚠️ Missing env vars: TELEGRAM_TOKEN, EMAIL_SENDER, EMAIL_PASSWORD")

# ===== LOGGING =====
def log_terminal(msg_type, message):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{waktu}] [{msg_type}] {message}", flush=True)

# ===== LOG EMAIL =====
def log_email_to_csv(subject, to, status):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile("email_log.csv")
    with open("email_log.csv", mode="a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["timestamp", "to", "subject", "status"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({"timestamp": waktu, "to": to, "subject": subject, "status": status})

# ===== LOG TELEGRAM =====
def log_message_to_csv(user, text):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile("message_log.csv")
    with open("message_log.csv", mode="a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["timestamp", "user", "username", "message"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": waktu,
            "user": user.first_name or "User",
            "username": user.username or "-",
            "message": text
        })

# ===== KIRIM EMAIL =====
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

    status = "Terkirim"
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log_terminal("EMAIL", f"Terkirim ke {msg['To']} | Subject: '{subject}'")
    except Exception as e:
        status = f"Gagal: {e}"
        log_terminal("EMAIL", f"Gagal kirim ke {msg['To']} | Error: {e}")

    log_email_to_csv(subject, msg["To"], status)
    return status

# ===== FORMAT WAKTU =====
def get_waktu_sekarang():
    hari_list = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    bulan_list = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    now = datetime.now()
    return f"{hari_list[now.weekday()]}, {now.day} {bulan_list[now.month - 1]} {now.year} • {now.strftime('%H:%M')}"

# ===== BUFFER DAN FLUSH =====
async def flush_pending_messages(context):
    if not context.bot_data.get("pending_messages"):
        return
    combined = context.bot_data["pending_messages"]
    context.bot_data["pending_messages"] = []

    body = ""
    attachments = []
    for m in combined:
        body += f"\n---\nDari: {m['from']}\nPesan:\n{m['text']}\n"
        attachments.extend(m["attachments"])

    subject = f"From Baba & Ibun – {get_waktu_sekarang()}"
    send_email(subject, body, attachments)
    for f in attachments:
        try:
            os.remove(f)
        except:
            pass
    log_terminal("SYSTEM", f"✅ {len(combined)} pesan terkirim ke email.")

# ===== COMMANDS =====
async def send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await flush_pending_messages(context)
    await update.message.reply_text("🚀 Semua pesan tertunda sudah dikirim.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya bot kamu 😄 Kirim pesan atau gambar, nanti saya kirim ke email otomatis.")

# ===== HANDLE PESAN =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or update.message.caption or "(tidak ada teks)"
    attachments = []

    os.makedirs("downloads", exist_ok=True)

    # Foto / Dokumen / Video
    if update.message.photo:
        photo = update.message.photo[-1]
        f = await photo.get_file()
        path = f"downloads/photo_{photo.file_id}.jpg"
        await f.download_to_drive(custom_path=path)
        attachments.append(path)
    if update.message.document:
        doc = update.message.document
        f = await doc.get_file()
        path = f"downloads/{doc.file_name}"
        await f.download_to_drive(custom_path=path)
        attachments.append(path)
    if update.message.video:
        video = update.message.video
        f = await video.get_file()
        path = f"downloads/video_{video.file_id}.mp4"
        await f.download_to_drive(custom_path=path)
        attachments.append(path)

    log_terminal("TELEGRAM", f"{user.first_name or 'User'}: {text}")
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
    await update.message.reply_text("✅ Pesan kamu diterima. Akan dikirim setelah 1 menit tanpa pesan baru.")

# ===== FLASK KEEPALIVE =====
flask_app = Flask("keepalive")

@flask_app.route("/")
def home():
    return "Bot running (Polling Mode) ✅", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ===== MAIN LOOP =====
if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=run_flask, daemon=True).start()

    while True:
        try:
            log_terminal("SYSTEM", "🤖 Bot aktif di Render (Polling Mode)...")
            app = Application.builder().token(TELEGRAM_TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("sent", send_now))
            app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
            app.run_polling(allowed_updates=Update.ALL_TYPES)
        except Conflict:
            log_terminal("SYSTEM", "⚠️ Bot lain masih aktif. Tunggu 20 detik dan coba lagi...")
            time.sleep(20)
        except TimedOut:
            log_terminal("SYSTEM", "⏱ Timeout, reconnect dalam 5 detik...")
            time.sleep(5)
        except KeyboardInterrupt:
            log_terminal("SYSTEM", "🛑 Bot dihentikan manual.")
            break
