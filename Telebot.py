import os
import smtplib
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from datetime import datetime
import locale
import warnings
import csv
import time
from telegram.error import TimedOut

# ===== SUPPRESS WARNING =====
warnings.filterwarnings("ignore", category=UserWarning, module="apscheduler")

# ===== KONFIGURASI ENV =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "abriellarayasha@gmail.com").split(",")

if not TELEGRAM_TOKEN or not EMAIL_SENDER or not EMAIL_PASSWORD:
    raise EnvironmentError("⚠️ Missing environment variables! Please set TELEGRAM_TOKEN, EMAIL_SENDER, and EMAIL_PASSWORD.")

# ===== SET LOKALISASI =====
try:
    locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8')
except:
    locale.setlocale(locale.LC_TIME, '')

# ===== LOGGING DI TERMINAL =====
def log_terminal(msg_type, message):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{waktu}] [{msg_type}] {message}")

# ===== SIMPAN LOG EMAIL =====
def log_email_to_csv(subject, to, status):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = "email_log.csv"
    file_exists = os.path.isfile(filename)
    with open(filename, mode="a", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["timestamp", "to", "subject", "status"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({"timestamp": waktu, "to": to, "subject": subject, "status": status})

# ===== SIMPAN LOG PESAN TELEGRAM =====
def log_message_to_csv(user, text):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = "message_log.csv"
    file_exists = os.path.isfile(filename)
    with open(filename, mode="a", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["timestamp", "user", "username", "message"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": waktu,
            "user": user.first_name or "User",
            "username": user.username or "-",
            "message": text
        })

# ===== KIRIM EMAIL DENGAN ATTACHMENT =====
def send_email(subject, body_text, attachments=None):
    msg = MIMEMultipart()
    msg["Subject"] = subject
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
        log_terminal("EMAIL", f"Gagal kirim ke {msg['To']} | Subject: '{subject}' | Error: {e}")

    log_email_to_csv(subject, msg["To"], status)
    return status

# ===== HANDLER TELEGRAM =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya adalah bot kamu.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or ""
    attachments = []

    # ===== DOWNLOAD PHOTO =====
    if update.message.photo:
        photo = update.message.photo[-1]  # Ambil resolusi terbesar
        file = await photo.get_file()
        path = f"downloads/photo_{photo.file_id}.jpg"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    # ===== DOWNLOAD DOCUMENT =====
    if update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        path = f"downloads/{doc.file_name}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    # ===== DOWNLOAD VIDEO =====
    if update.message.video:
        video = update.message.video
        file = await video.get_file()
        path = f"downloads/video_{video.file_id}.mp4"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await file.download_to_drive(custom_path=path)
        attachments.append(path)

    # ===== LOG TELEGRAM =====
    log_terminal("TELEGRAM", f"Dari: {user.first_name or 'User'} (@{user.username or '-'}) | Pesan: {text} | Attachments: {len(attachments)}")
    log_message_to_csv(user, text)

    # ===== SET SUBJECT DENGAN WAKTU =====
    now = datetime.now()
    # Coba format Indonesia tapi pastikan jam & menit selalu ada
    try:
        waktu_sekarang = f"{now.strftime('%A, %d %B %Y')} • {now.strftime('%H:%M')}"
    except:
        # fallback jika locale gagal
        waktu_sekarang = now.strftime("%Y-%m-%d %H:%M")

    subject = f"From Baba & Ibun – {waktu_sekarang}"
    body = f"Dari: {user.first_name or 'User'} (@{user.username or '-'})\nPesan:\n{text}"

    # ===== KIRIM EMAIL =====
    email_status = send_email(subject, body, attachments)

    # ===== BALAS KE USER =====
    if email_status == "Terkirim":
        await update.message.reply_text("✅ Pesan kamu sudah dikirim ke email Biel & dicatat di log.")
    else:
        await update.message.reply_text(f"❌ Terjadi kesalahan saat mengirim email:\n{email_status}")

# ===== BUILD BOT =====
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

# ===== RUN BOT =====
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    while True:
        try:
            log_terminal("SYSTEM", "🤖 Bot sedang berjalan... Tekan Ctrl+C untuk berhenti.")
            app.run_polling()
        except TimedOut:
            log_terminal("SYSTEM", "⏱ Timeout terjadi, mencoba lagi dalam 5 detik...")
            time.sleep(5)
        except KeyboardInterrupt:
            log_terminal("SYSTEM", "🛑 Bot dihentikan secara manual.")
            break
