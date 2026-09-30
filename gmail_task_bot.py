#!/usr/bin/env python3
"""Gmail Task Bot — button-only, Bot API 9.4 colored buttons + Premium custom emoji.
Theme copied from BytoVEX (ib/kb helpers, <tg-emoji>, blockquote sections).

ENV: BOT_TOKEN, ADMIN_ID, DB_PATH (optional)
pip install "aiogram>=3.25"
"""
import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiohttp import web
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "gmailtask.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("gmailbot")

IST = timezone(timedelta(hours=5, minutes=30))
def now_ist() -> datetime: return datetime.now(IST)
def stamp() -> str: return now_ist().strftime("%Y-%m-%d %H:%M:%S")

# ───────────────────────── THEME (premium emoji + colored buttons) ─────────────────────────
def e(emoji_id: int, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

M_VERIFIED = e(5406690851533370477, "✅")
M_CHECK    = e(6041919344995209164, "✅")
M_CROSS    = e(6037254263187443802, "❌")
M_WALLET   = e(6042098561095570207, "👛")
M_MONEY    = e(5904462880941545555, "💰")
M_DOLLAR   = e(5902206159095339799, "💵")
M_BULB     = e(5767288287001580715, "💡")
M_SHIELD   = e(6030445631921721471, "🛡")
M_CROWN    = e(5805553606635559688, "👑")
M_LIST     = e(5408876620519848175, "📋")
M_LOADING  = e(5843679481566335204, "⏳")
M_WARN     = e(5408943604829794451, "⚠️")
M_FIRE     = e(5408849420491962048, "🔥")
M_TARGET   = e(5904650558127478452, "🎯")
M_LOCK     = e(6037249452824072506, "🔒")
M_BELL     = e(6039486778597970865, "🔔")
M_TICKET   = e(5891104106721844396, "🎫")
M_CHART    = e(5938539885907415367, "📊")
M_GEAR     = e(5904258298764334001, "⚙️")
M_TAP      = e(6039779802741739617, "👆")
M_TYPE     = e(6039404727542747508, "⌨️")
M_MEGA     = e(6039381989985882045, "📣")
M_SPARKLE  = e(5890925363067886150, "✨")
M_DIAMOND  = e(6037083366438737901, "💎")
QMARK = [e(i, "✅") for i in (5938252440926163756, 5408909562919007848, 5409029658794537988,
                              6032850693348399258, 6030839471832829491, 5805550320985578625)]

# button icon ids
B_CREATE, B_MYGM = "5938537205847822613", "5938492039971737551"
B_WALLET, B_SHIELD, B_BULB, B_CROWN = "6042098561095570207", "6030445631921721471", "5767288287001580715", "5805553606635559688"
B_BACK, B_CANCEL, B_CHECK = "6035130900075777681", "5774077015388852135", "6041919344995209164"
B_MONEY, B_HIST, B_DOLLAR = "5904462880941545555", "5776118099812028333", "5902206159095339799"
B_GEAR, B_CHART, B_USER, B_MEGA = "5904258298764334001", "5938539885907415367", "6032693626394382504", "6039381989985882045"
B_LOCK, B_LIST, B_TICKET, B_EDIT = "6037249452824072506", "5408876620519848175", "5891104106721844396", "6039614175917903752"
B_REFRESH, B_PLUS, B_TG, B_BELL = "5850346984501680054", "5771851822897566479", "5927118708873892465", "6039486778597970865"

def ib(text, style="primary", icon=None, **kw) -> InlineKeyboardButton:
    if icon: kw["icon_custom_emoji_id"] = icon
    try:
        return InlineKeyboardButton(text=text, style=style, **kw)
    except TypeError:
        kw.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(text=text, **kw)

def kb(text, style="primary", icon=None) -> KeyboardButton:
    kw = {"icon_custom_emoji_id": icon} if icon else {}
    try:
        return KeyboardButton(text=text, style=style, **kw)
    except TypeError:
        return KeyboardButton(text=text)

def ik(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])

def q(i: int, text: str) -> str:
    """Blockquote section with a marker emoji on every line."""
    m = QMARK[i % len(QMARK)]
    return "<blockquote>" + "\n".join(f"{m} {ln}" for ln in text.split("\n")) + "</blockquote>"

BTN_CREATE, BTN_MYGM, BTN_WALLET = "Create Gmail", "My Gmails", "Wallet"
BTN_SUPPORT, BTN_HELP, BTN_ADMIN = "Support", "Help", "Admin Panel"

def main_kb(uid: int) -> ReplyKeyboardMarkup:
    rows = [[kb(BTN_CREATE, "success", B_CREATE), kb(BTN_MYGM, "primary", B_MYGM)],
            [kb(BTN_WALLET, "primary", B_WALLET), kb(BTN_SUPPORT, "success", B_SHIELD)],
            [kb(BTN_HELP, "primary", B_BULB)]]
    if uid == ADMIN_ID:
        rows.append([kb(BTN_ADMIN, "danger", B_CROWN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ───────────────────────── DATABASE ─────────────────────────
DEFAULTS = {"task_open": "0", "password": "", "rate": "5", "usd_rate": "85",
            "min_upi": "20", "min_binance": "1", "min_bep20": "3", "daily_limit": "20"}

def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT, username TEXT,
            balance REAL DEFAULT 0, total_earned REAL DEFAULT 0, joined TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            gmail TEXT, gmail_norm TEXT UNIQUE, status TEXT DEFAULT 'pending', reason TEXT,
            amount REAL DEFAULT 0, created TEXT, reviewed TEXT);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount REAL, kind TEXT, ref TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            method TEXT, detail TEXT, amount_inr REAL, amount_disp TEXT, status TEXT DEFAULT 'pending',
            created TEXT);
        """)
        for k, v in DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))

def gs(key: str) -> str:
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else DEFAULTS.get(key, "")

def gf(key: str) -> float:
    try: return float(gs(key))
    except ValueError: return float(DEFAULTS.get(key, 0) or 0)

def ss(key: str, value: str):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))

def ensure_user(u):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id,name,username,joined) VALUES(?,?,?,?)",
                  (u.id, u.first_name or "", u.username or "", stamp()))

def user_row(uid: int):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def ledger_add(c, uid: int, amount: float, kind: str, ref: str = ""):
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
    if kind == "credit":
        c.execute("UPDATE users SET total_earned=total_earned+? WHERE user_id=?", (amount, uid))
    c.execute("INSERT INTO ledger(user_id,amount,kind,ref,created) VALUES(?,?,?,?,?)",
              (uid, amount, kind, ref, stamp()))

def inr(x: float) -> str: return f"₹{x:,.2f}"
def usd(x_inr: float) -> str: return f"${x_inr / max(gf('usd_rate'), 0.0001):,.2f}"

# ───────────────────────── STATES / SETUP ─────────────────────────
class S(StatesGroup):
    gmail = State(); wd_detail = State(); wd_amount = State(); support = State()

class A(StatesGroup):
    reason = State(); setting = State(); broadcast = State(); reply = State()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) if BOT_TOKEN else None
dp = Dispatcher(storage=MemoryStorage())
r = Router(name="user")
adm = Router(name="admin")
adm.message.filter(F.from_user.id == ADMIN_ID)
adm.callback_query.filter(F.from_user.id == ADMIN_ID)

async def edit(cb: CallbackQuery, text: str, markup=None):
    """Smooth UI: edit in place; fall back to a fresh message if the old one can't be edited."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as ex:
        if "not modified" not in str(ex):
            await cb.message.answer(text, reply_markup=markup)

def cancel_ik(cb="cancel_flow"):
    return ik([ib("Cancel", "danger", B_CANCEL, callback_data=cb)])

GMAIL_RE = re.compile(r"^[a-z0-9][a-z0-9.]{4,28}[a-z0-9]@gmail\.com$")
def gmail_norm(addr: str) -> str:
    local, dom = addr.split("@")
    return local.replace(".", "") + "@" + dom

# ───────────────────────── USER: START + MENU ─────────────────────────
@r.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    await state.clear(); ensure_user(msg.from_user)
    await msg.answer(
        f"{M_VERIFIED} <b>Welcome, {msg.from_user.first_name or 'Friend'}!</b>\n\n"
        f"{M_FIRE} <b>How it works</b>\n"
        + q(1, "Tap Create Gmail and follow the steps\nSubmit the new Gmail address\nGet paid after admin approval\nWithdraw via UPI, Binance ID or BEP20") +
        f"\n\n{M_TARGET} <b>Choose an option below</b> {M_TAP}",
        reply_markup=main_kb(msg.from_user.id))

@r.message(F.text == BTN_CREATE)
async def create_gmail(msg: Message, state: FSMContext):
    await state.clear(); ensure_user(msg.from_user)
    if gs("task_open") != "1":
        return await msg.answer(f"{M_LOCK} <b>No task available</b>\n" +
                                q(2, "The task is currently closed.\nYou'll be notified when it opens."))
    pw = gs("password")
    if not pw:
        return await msg.answer(f"{M_WARN} <b>Task not ready yet.</b> Please check back soon.")
    await msg.answer(
        f"{M_LIST} <b>Create a Gmail account</b>\n"
        f"<i>Use exactly these details</i>\n\n"
        + q(0, "First name: <b>any</b>\nLast name: <b>any</b>\n"
               f"Password: <code>{pw}</code>\nDate of birth: <b>any date between 1995 – 2000</b>") +
        f"\n\n{M_BULB} <b>After creating</b>\n"
        + q(3, "Tap Submit Gmail and send the address (name@gmail.com)\nAdmin reviews it, then your wallet is credited") +
        f"\n\n{M_MONEY} <b>Reward:</b> {inr(gf('rate'))} per approved Gmail",
        reply_markup=ik([ib("Submit Gmail", "success", B_CHECK, callback_data="gm_submit")],
                        [ib("Back", "danger", B_BACK, callback_data="gm_back")]))

@r.callback_query(F.data == "gm_back")
async def gm_back(cb: CallbackQuery):
    await cb.answer()
    try: await cb.message.delete()
    except TelegramBadRequest: pass

@r.callback_query(F.data == "gm_submit")
async def gm_submit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if gs("task_open") != "1":
        return await edit(cb, f"{M_LOCK} <b>The task was just closed.</b>")
    with db() as c:
        n = c.execute("SELECT COUNT(*) n FROM submissions WHERE user_id=? AND created>=?",
                      (cb.from_user.id, now_ist().strftime("%Y-%m-%d"))).fetchone()["n"]
    if n >= gf("daily_limit"):
        return await edit(cb, f"{M_WARN} <b>Daily limit reached</b>\n" + q(2, "Try again tomorrow."))
    await state.set_state(S.gmail)
    await edit(cb, f"{M_TYPE} <b>Send your new Gmail address</b>\n" + q(4, "Format: <code>name@gmail.com</code>"),
               cancel_ik())

@r.callback_query(F.data == "cancel_flow")
async def cancel_flow(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.answer("Cancelled")
    await edit(cb, f"{M_CROSS} <b>Cancelled</b>")

@r.message(S.gmail, F.text)
async def got_gmail(msg: Message, state: FSMContext):
    addr = msg.text.strip().lower()
    if not GMAIL_RE.match(addr):
        return await msg.answer(f"{M_WARN} <b>Invalid format.</b> Send like <code>name@gmail.com</code>",
                                reply_markup=cancel_ik())
    try:
        with db() as c:
            cur = c.execute("INSERT INTO submissions(user_id,gmail,gmail_norm,created) VALUES(?,?,?,?)",
                            (msg.from_user.id, addr, gmail_norm(addr), stamp()))
            sid = cur.lastrowid
    except sqlite3.IntegrityError:
        return await msg.answer(f"{M_CROSS} <b>This Gmail was already submitted.</b>", reply_markup=cancel_ik())
    await state.clear()
    await msg.answer(f"{M_LOADING} <b>Submitted for review</b>\n" +
                     q(1, f"Gmail: <code>{addr}</code>\nStatus: Pending approval"),
                     reply_markup=main_kb(msg.from_user.id))
    await bot.send_message(ADMIN_ID, review_text(sid), reply_markup=review_ik(sid))

def review_text(sid: int) -> str:
    with db() as c:
        s = c.execute("SELECT s.*, u.name, u.username FROM submissions s JOIN users u USING(user_id) WHERE s.id=?",
                      (sid,)).fetchone()
    uname = f"@{s['username']}" if s["username"] else s["name"]
    return (f"{M_BELL} <b>New Gmail submission #{sid}</b>\n" +
            q(0, f"User: {uname} (<code>{s['user_id']}</code>)\nGmail: <code>{s['gmail']}</code>\nTime: {s['created']}"))

def review_ik(sid: int):
    return ik([ib("Approve", "success", B_CHECK, callback_data=f"ap_{sid}"),
               ib("Reject", "danger", B_CANCEL, callback_data=f"rej_{sid}")])

@r.message(F.text == BTN_MYGM)
async def my_gmails(msg: Message, state: FSMContext):
    await state.clear()
    with db() as c:
        rows = c.execute("SELECT * FROM submissions WHERE user_id=? ORDER BY id DESC LIMIT 15",
                         (msg.from_user.id,)).fetchall()
    if not rows:
        return await msg.answer(f"{M_LIST} <b>My Gmails</b>\n" + q(2, "You haven't submitted any yet."))
    icons = {"pending": M_LOADING, "approved": M_CHECK, "rejected": M_CROSS}
    lines = []
    for s in rows:
        ln = f"{icons[s['status']]} <code>{s['gmail']}</code> — {s['status'].title()}"
        if s["status"] == "rejected" and s["reason"]:
            ln += f"\n      <i>Reason: {s['reason']}</i>"
        lines.append(ln)
    await msg.answer(f"{M_LIST} <b>My Gmails</b> <i>(latest 15)</i>\n\n" + "\n".join(lines))

# ───────────────────────── USER: WALLET + WITHDRAW ─────────────────────────
METHODS = {
    "upi":     ("UPI", "₹", "min_upi", "Enter your <b>UPI ID</b> (e.g. <code>name@upi</code>)",
                re.compile(r"^[\w.\-]{2,}@[a-zA-Z]{2,}$")),
    "binance": ("Binance ID", "$", "min_binance", "Enter your <b>Binance Pay ID</b> (numbers only)",
                re.compile(r"^\d{5,15}$")),
    "bep20":   ("BEP20", "$", "min_bep20", "Enter your <b>BEP20 (BSC) address</b> starting with 0x",
                re.compile(r"^0x[a-fA-F0-9]{40}$")),
}

def wallet_text(uid: int) -> str:
    u = user_row(uid)
    with db() as c:
        held = c.execute("SELECT COALESCE(SUM(amount_inr),0) s FROM withdrawals WHERE user_id=? AND status='pending'",
                         (uid,)).fetchone()["s"]
    return (f"{M_WALLET} <b>My Wallet</b>\n\n" +
            q(0, f"Balance: <b>{inr(u['balance'])}</b> (≈ {usd(u['balance'])})\nTotal earned: {inr(u['total_earned'])}"
                 f"\nPending withdrawals: {inr(held)}") +
            f"\n\n{M_DOLLAR} <b>Minimum withdrawal</b>\n" +
            q(3, f"UPI: ₹{gf('min_upi'):g}\nBinance ID: ${gf('min_binance'):g}\nBEP20: ${gf('min_bep20'):g}"))

def wallet_ik():
    return ik([ib("Withdraw", "success", B_MONEY, callback_data="wd_start")],
              [ib("History", "primary", B_HIST, callback_data="wd_hist")])

@r.message(F.text == BTN_WALLET)
async def wallet(msg: Message, state: FSMContext):
    await state.clear(); ensure_user(msg.from_user)
    await msg.answer(wallet_text(msg.from_user.id), reply_markup=wallet_ik())

@r.callback_query(F.data == "wd_back")
async def wd_back(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.answer()
    await edit(cb, wallet_text(cb.from_user.id), wallet_ik())

@r.callback_query(F.data == "wd_hist")
async def wd_hist(cb: CallbackQuery):
    await cb.answer()
    with db() as c:
        rows = c.execute("SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 10", (cb.from_user.id,)).fetchall()
    body = "\n".join(f"{'+' if x['amount'] >= 0 else '−'}{inr(abs(x['amount']))} · {x['kind']} · {x['created'][:16]}"
                     for x in rows) or "No transactions yet."
    await edit(cb, f"{M_LIST} <b>Transaction history</b>\n" + q(4, body),
               ik([ib("Back", "danger", B_BACK, callback_data="wd_back")]))

@r.callback_query(F.data == "wd_start")
async def wd_start(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.answer()
    await edit(cb, f"{M_MONEY} <b>Choose withdrawal method</b> {M_TAP}",
               ik([ib("UPI", "success", B_MONEY, callback_data="wdm_upi")],
                  [ib("Binance ID", "primary", B_DOLLAR, callback_data="wdm_binance"),
                   ib("BEP20", "primary", B_DOLLAR, callback_data="wdm_bep20")],
                  [ib("Back", "danger", B_BACK, callback_data="wd_back")]))

@r.callback_query(F.data.startswith("wdm_"))
async def wd_method(cb: CallbackQuery, state: FSMContext):
    m = cb.data[4:]; name, cur, mk, prompt, _ = METHODS[m]
    await cb.answer()
    await state.update_data(method=m); await state.set_state(S.wd_detail)
    await edit(cb, f"{M_TYPE} {prompt}", cancel_ik("wd_back"))

@r.message(S.wd_detail, F.text)
async def wd_detail(msg: Message, state: FSMContext):
    d = await state.get_data(); name, cur, mk, prompt, rx = METHODS[d["method"]]
    detail = msg.text.strip()
    if not rx.match(detail):
        return await msg.answer(f"{M_WARN} <b>Invalid {name}.</b> Please check and send again.",
                                reply_markup=cancel_ik("wd_back"))
    await state.update_data(detail=detail); await state.set_state(S.wd_amount)
    await msg.answer(f"{M_TYPE} <b>Enter amount in {cur}</b>\n" + q(3, f"Minimum: {cur}{gf(mk):g}"),
                     reply_markup=ik([ib("Withdraw All", "success", B_MONEY, callback_data="wd_all")],
                                     [ib("Cancel", "danger", B_CANCEL, callback_data="wd_back")]))

async def finish_withdraw(target, uid: int, state: FSMContext, amount: Optional[float]):
    d = await state.get_data(); m = d["method"]; name, cur, mk, _, _ = METHODS[m]
    bal = user_row(uid)["balance"]; rate = 1 if cur == "₹" else gf("usd_rate")
    if amount is None:                                     # withdraw all
        amount = bal / rate
        amount = int(amount * 100) / 100
    inr_amt = amount * rate
    if amount < gf(mk):
        return await target.answer(f"{M_WARN} <b>Below minimum</b> ({cur}{gf(mk):g}).", reply_markup=cancel_ik("wd_back"))
    if inr_amt > bal + 1e-9:
        return await target.answer(f"{M_WARN} <b>Insufficient balance.</b> You have {inr(bal)}.", reply_markup=cancel_ik("wd_back"))
    with db() as c:   # hold funds now; refunded automatically if admin rejects
        cur_ = c.execute("INSERT INTO withdrawals(user_id,method,detail,amount_inr,amount_disp,created) VALUES(?,?,?,?,?,?)",
                         (uid, m, d["detail"], inr_amt, f"{cur}{amount:g}", stamp()))
        wid = cur_.lastrowid
        ledger_add(c, uid, -inr_amt, "withdraw_hold", f"W{wid}")
    await state.clear()
    await target.answer(f"{M_LOADING} <b>Withdrawal requested</b>\n" +
                        q(1, f"Method: {name}\nAmount: {cur}{amount:g}\nStatus: Pending"),
                        reply_markup=main_kb(uid))
    await bot.send_message(ADMIN_ID, wd_text(wid), reply_markup=wd_ik(wid))

@r.message(S.wd_amount, F.text)
async def wd_amount(msg: Message, state: FSMContext):
    try: amt = float(msg.text.replace(",", ".").strip())
    except ValueError: return await msg.answer(f"{M_WARN} <b>Send a number.</b>", reply_markup=cancel_ik("wd_back"))
    if amt <= 0: return await msg.answer(f"{M_WARN} <b>Amount must be positive.</b>", reply_markup=cancel_ik("wd_back"))
    await finish_withdraw(msg, msg.from_user.id, state, amt)

@r.callback_query(S.wd_amount, F.data == "wd_all")
async def wd_all(cb: CallbackQuery, state: FSMContext):
    await cb.answer(); await finish_withdraw(cb.message, cb.from_user.id, state, None)

def wd_text(wid: int) -> str:
    with db() as c:
        w = c.execute("SELECT w.*, u.name, u.username FROM withdrawals w JOIN users u USING(user_id) WHERE w.id=?", (wid,)).fetchone()
    uname = f"@{w['username']}" if w["username"] else w["name"]
    return (f"{M_MONEY} <b>Withdrawal request #{wid}</b>\n" +
            q(0, f"User: {uname} (<code>{w['user_id']}</code>)\nMethod: {METHODS[w['method']][0]}\n"
                 f"To: <code>{w['detail']}</code>\nAmount: <b>{w['amount_disp']}</b> ({inr(w['amount_inr'])})"))

def wd_ik(wid: int):
    return ik([ib("Paid", "success", B_CHECK, callback_data=f"wdp_{wid}"),
               ib("Reject", "danger", B_CANCEL, callback_data=f"wdr_{wid}")])

# ───────────────────────── USER: SUPPORT + HELP ─────────────────────────
@r.message(F.text == BTN_SUPPORT)
async def support(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(f"{M_SHIELD} <b>Support</b>\n" + q(2, "Need help? Send us a message and we'll reply here."),
                     reply_markup=ik([ib("Write to Support", "success", B_TICKET, callback_data="sup_start")]))

@r.callback_query(F.data == "sup_start")
async def sup_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer(); await state.set_state(S.support)
    await edit(cb, f"{M_TYPE} <b>Type your message</b>", cancel_ik())

@r.message(S.support, F.text)
async def sup_msg(msg: Message, state: FSMContext):
    await state.clear(); u = msg.from_user
    uname = f"@{u.username}" if u.username else u.first_name
    await bot.send_message(ADMIN_ID, f"{M_TICKET} <b>Support message</b> from {uname} (<code>{u.id}</code>)\n" +
                           q(3, msg.html_text),
                           reply_markup=ik([ib("Reply", "primary", B_EDIT, callback_data=f"sreply_{u.id}")]))
    await msg.answer(f"{M_CHECK} <b>Sent!</b> We'll reply here soon.", reply_markup=main_kb(u.id))

@r.message(F.text == BTN_HELP)
async def help_(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        f"{M_BULB} <b>Help Guide</b>\n\n"
        f"{M_LIST} <b>Creating a Gmail</b>\n" + q(0, "Tap Create Gmail (only when a task is open)\nFirst / last name: any\n"
                                                   "Password: the fixed one shown\nDOB: between 1995 and 2000") + "\n\n"
        f"{M_CHECK} <b>Submitting</b>\n" + q(1, "Send the address as name@gmail.com\nDuplicates are rejected\nAdmin approves or rejects with a reason") + "\n\n"
        f"{M_MONEY} <b>Payouts</b>\n" + q(3, f"Approved Gmail = {inr(gf('rate'))}\nUPI min ₹{gf('min_upi'):g}\n"
                                            f"Binance ID min ${gf('min_binance'):g}\nBEP20 min ${gf('min_bep20'):g}") + "\n\n"
        f"{M_SHIELD} Need help? Tap <b>Support</b> {M_TAP}")

# ───────────────────────── ADMIN ─────────────────────────
def panel_ik():
    o = gs("task_open") == "1"
    return ik([ib("Close Task" if o else "Open Task", "danger" if o else "success", B_LOCK, callback_data="adm_toggle")],
              [ib("Pending Reviews", "primary", B_LIST, callback_data="adm_pending"),
               ib("Withdrawals", "primary", B_MONEY, callback_data="adm_wds")],
              [ib("Users", "primary", B_USER, callback_data="adm_users"),
               ib("Stats", "success", B_CHART, callback_data="adm_stats")],
              [ib("Settings", "primary", B_GEAR, callback_data="adm_settings"),
               ib("Broadcast", "success", B_MEGA, callback_data="adm_bc")],
              [ib("Close", "danger", B_BACK, callback_data="adm_close")])

def panel_text():
    o = gs("task_open") == "1"
    return (f"{M_CROWN} <b>Admin Panel</b>\n" +
            q(0, f"Task: {'🟢 OPEN' if o else '🔴 CLOSED'}\nReward: {inr(gf('rate'))} per Gmail"))

@r.message(F.text == BTN_ADMIN)
async def admin_panel(msg: Message, state: FSMContext):
    await state.clear()
    if msg.from_user.id != ADMIN_ID: return
    await msg.answer(panel_text(), reply_markup=panel_ik())

@adm.callback_query(F.data == "adm_home")
async def adm_home(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.answer(); await edit(cb, panel_text(), panel_ik())

@adm.callback_query(F.data == "adm_close")
async def adm_close(cb: CallbackQuery):
    await cb.answer()
    try: await cb.message.delete()
    except TelegramBadRequest: pass

@adm.callback_query(F.data == "adm_toggle")
async def adm_toggle(cb: CallbackQuery):
    now_open = gs("task_open") != "1"
    if now_open and not gs("password"):
        return await cb.answer("Set the password first (Settings).", show_alert=True)
    ss("task_open", "1" if now_open else "0")
    await cb.answer("Task opened" if now_open else "Task closed")
    await edit(cb, panel_text(), panel_ik())
    if now_open:
        with db() as c: ids = [x["user_id"] for x in c.execute("SELECT user_id FROM users")]
        for uid in ids:
            if uid == ADMIN_ID: continue
            try:
                await bot.send_message(uid, f"{M_BELL} <b>A new task is open!</b>\nTap <b>Create Gmail</b> {M_TAP}")
            except Exception: pass
            await asyncio.sleep(0.05)

# --- review approve / reject
@adm.callback_query(F.data.startswith("ap_"))
async def approve(cb: CallbackQuery):
    sid = int(cb.data[3:]); amt = gf("rate")
    with db() as c:
        s = c.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        cur = c.execute("UPDATE submissions SET status='approved',amount=?,reviewed=? WHERE id=? AND status='pending'",
                        (amt, stamp(), sid))
        if cur.rowcount:
            ledger_add(c, s["user_id"], amt, "credit", f"S{sid}")
    if not cur.rowcount: return await cb.answer("Already handled.", show_alert=True)
    await cb.answer("Approved")
    await edit(cb, review_text(sid) + f"\n\n{M_CHECK} <b>Approved — {inr(amt)} credited</b>")
    try:
        await bot.send_message(s["user_id"], f"{M_CHECK} <b>Gmail approved!</b>\n" +
                               q(1, f"<code>{s['gmail']}</code>\n{inr(amt)} added to your wallet"))
    except Exception: pass

@adm.callback_query(F.data.startswith("rej_"))
async def reject(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data[4:]); await cb.answer()
    await state.update_data(sid=sid, msg_id=cb.message.message_id); await state.set_state(A.reason)
    await cb.message.answer(f"{M_TYPE} <b>Type the rejection reason for #{sid}</b>",
                            reply_markup=cancel_ik("adm_home"))

@adm.message(A.reason, F.text)
async def reject_reason(msg: Message, state: FSMContext):
    d = await state.get_data(); sid = d["sid"]; reason = msg.text.strip()[:300]
    with db() as c:
        s = c.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        cur = c.execute("UPDATE submissions SET status='rejected',reason=?,reviewed=? WHERE id=? AND status='pending'",
                        (reason, stamp(), sid))
    await state.clear()
    if not cur.rowcount: return await msg.answer("Already handled.")
    await msg.answer(f"{M_CROSS} <b>#{sid} rejected.</b>")
    try:
        await bot.edit_message_text(review_text(sid) + f"\n\n{M_CROSS} <b>Rejected:</b> {reason}",
                                    chat_id=ADMIN_ID, message_id=d["msg_id"])
    except Exception: pass
    try:
        await bot.send_message(s["user_id"], f"{M_CROSS} <b>Gmail rejected</b>\n" +
                               q(2, f"<code>{s['gmail']}</code>\nReason: {reason}"))
    except Exception: pass

@adm.callback_query(F.data == "adm_pending")
async def adm_pending(cb: CallbackQuery):
    with db() as c:
        ids = [x["id"] for x in c.execute("SELECT id FROM submissions WHERE status='pending' ORDER BY id LIMIT 10")]
    await cb.answer()
    if not ids: return await cb.message.answer(f"{M_CHECK} <b>No pending reviews.</b>")
    for sid in ids: await cb.message.answer(review_text(sid), reply_markup=review_ik(sid))

# --- withdrawals
@adm.callback_query(F.data.startswith("wdp_"))
async def wd_paid(cb: CallbackQuery):
    wid = int(cb.data[4:])
    with db() as c:
        w = c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        cur = c.execute("UPDATE withdrawals SET status='paid' WHERE id=? AND status='pending'", (wid,))
    if not cur.rowcount: return await cb.answer("Already handled.", show_alert=True)
    await cb.answer("Marked paid")
    await edit(cb, wd_text(wid) + f"\n\n{M_CHECK} <b>Paid</b>")
    try:
        await bot.send_message(w["user_id"], f"{M_CHECK} <b>Payment sent!</b>\n" +
                               q(1, f"{w['amount_disp']} via {METHODS[w['method']][0]}"))
    except Exception: pass

@adm.callback_query(F.data.startswith("wdr_"))
async def wd_reject(cb: CallbackQuery):
    wid = int(cb.data[4:])
    with db() as c:
        w = c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        cur = c.execute("UPDATE withdrawals SET status='rejected' WHERE id=? AND status='pending'", (wid,))
        if cur.rowcount: ledger_add(c, w["user_id"], w["amount_inr"], "withdraw_refund", f"W{wid}")
    if not cur.rowcount: return await cb.answer("Already handled.", show_alert=True)
    await cb.answer("Rejected & refunded")
    await edit(cb, wd_text(wid) + f"\n\n{M_CROSS} <b>Rejected — refunded</b>")
    try:
        await bot.send_message(w["user_id"], f"{M_CROSS} <b>Withdrawal rejected</b>\n" +
                               q(2, f"{w['amount_disp']} was returned to your wallet."))
    except Exception: pass

@adm.callback_query(F.data == "adm_wds")
async def adm_wds(cb: CallbackQuery):
    with db() as c:
        ids = [x["id"] for x in c.execute("SELECT id FROM withdrawals WHERE status='pending' ORDER BY id LIMIT 10")]
    await cb.answer()
    if not ids: return await cb.message.answer(f"{M_CHECK} <b>No pending withdrawals.</b>")
    for wid in ids: await cb.message.answer(wd_text(wid), reply_markup=wd_ik(wid))

# --- users / stats
@adm.callback_query(F.data == "adm_users")
async def adm_users(cb: CallbackQuery):
    with db() as c:
        n = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        top = c.execute("SELECT * FROM users ORDER BY total_earned DESC LIMIT 10").fetchall()
    body = "\n".join(f"{i}. {u['name'] or u['user_id']} — {inr(u['total_earned'])}" for i, u in enumerate(top, 1)) or "—"
    await cb.answer()
    await edit(cb, f"{M_CROWN} <b>Users:</b> {n}\n\n<b>Top earners</b>\n" + q(5, body),
               ik([ib("Back", "danger", B_BACK, callback_data="adm_home")]))

@adm.callback_query(F.data == "adm_stats")
async def adm_stats(cb: CallbackQuery):
    with db() as c:
        sub = {x["status"]: x["n"] for x in c.execute("SELECT status, COUNT(*) n FROM submissions GROUP BY status")}
        paid = c.execute("SELECT COALESCE(SUM(amount_inr),0) s FROM withdrawals WHERE status='paid'").fetchone()["s"]
        pend = c.execute("SELECT COALESCE(SUM(amount_inr),0) s FROM withdrawals WHERE status='pending'").fetchone()["s"]
        bal = c.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
    await cb.answer()
    await edit(cb, f"{M_CHART} <b>Stats</b>\n\n" +
               q(0, f"Pending: {sub.get('pending', 0)}\nApproved: {sub.get('approved', 0)}\nRejected: {sub.get('rejected', 0)}") + "\n\n" +
               q(1, f"Paid out: {inr(paid)}\nPending payouts: {inr(pend)}\nUser balances owed: {inr(bal)}"),
               ik([ib("Back", "danger", B_BACK, callback_data="adm_home")]))

# --- settings
SETTINGS = [("password", "Password", B_LOCK), ("rate", "Reward ₹", B_MONEY), ("usd_rate", "₹ per $1", B_DOLLAR),
            ("min_upi", "Min UPI ₹", B_MONEY), ("min_binance", "Min Binance $", B_DOLLAR),
            ("min_bep20", "Min BEP20 $", B_DOLLAR), ("daily_limit", "Daily limit", B_LIST)]

@adm.callback_query(F.data == "adm_settings")
async def adm_settings(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.answer()
    lines = "\n".join(f"{label}: <code>{gs(k) or 'not set'}</code>" for k, label, _ in SETTINGS)
    rows = [[ib(label, "primary" if i % 2 == 0 else "success", ic, callback_data=f"set_{k}")]
            for i, (k, label, ic) in enumerate(SETTINGS)]
    rows.append([ib("Back", "danger", B_BACK, callback_data="adm_home")])
    await edit(cb, f"{M_GEAR} <b>Settings</b> <i>(tap to change)</i>\n" + q(3, lines), ik(*rows))

@adm.callback_query(F.data.startswith("set_"))
async def set_pick(cb: CallbackQuery, state: FSMContext):
    key = cb.data[4:]; await cb.answer()
    await state.update_data(key=key); await state.set_state(A.setting)
    await edit(cb, f"{M_TYPE} <b>Send the new value for</b> <code>{key}</code>", cancel_ik("adm_settings"))

@adm.message(A.setting, F.text)
async def set_value(msg: Message, state: FSMContext):
    key = (await state.get_data())["key"]; val = msg.text.strip()
    if key != "password":
        try:
            if float(val) < 0: raise ValueError
        except ValueError:
            return await msg.answer(f"{M_WARN} <b>Send a valid number.</b>")
    ss(key, val); await state.clear()
    await msg.answer(f"{M_CHECK} <b>Updated</b> <code>{key}</code>", reply_markup=ik(
        [ib("Back to Settings", "primary", B_GEAR, callback_data="adm_settings")]))

# --- broadcast / support reply
@adm.callback_query(F.data == "adm_bc")
async def adm_bc(cb: CallbackQuery, state: FSMContext):
    await cb.answer(); await state.set_state(A.broadcast)
    await edit(cb, f"{M_MEGA} <b>Send the broadcast message</b>", cancel_ik("adm_home"))

@adm.message(A.broadcast, F.text)
async def do_bc(msg: Message, state: FSMContext):
    await state.clear()
    with db() as c: ids = [x["user_id"] for x in c.execute("SELECT user_id FROM users")]
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, f"{M_MEGA} {msg.html_text}"); ok += 1
        except Exception: pass
        await asyncio.sleep(0.05)
    await msg.answer(f"{M_CHECK} <b>Sent to {ok}/{len(ids)} users.</b>")

@adm.callback_query(F.data.startswith("sreply_"))
async def sreply(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data[7:]); await cb.answer()
    await state.update_data(uid=uid); await state.set_state(A.reply)
    await cb.message.answer(f"{M_TYPE} <b>Type your reply</b>", reply_markup=cancel_ik("adm_home"))

@adm.message(A.reply, F.text)
async def do_reply(msg: Message, state: FSMContext):
    uid = (await state.get_data())["uid"]; await state.clear()
    try:
        await bot.send_message(uid, f"{M_SHIELD} <b>Support reply</b>\n" + q(1, msg.html_text))
        await msg.answer(f"{M_CHECK} <b>Reply sent.</b>")
    except Exception:
        await msg.answer(f"{M_WARN} <b>Couldn't deliver</b> (user may have blocked the bot).")

# ───────────────────────── RUN ─────────────────────────
async def run_web():
    """Tiny HTTP server so Render's web service sees an open port."""
    async def health(_):
        return web.Response(text="ok")
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000"))).start()
    log.info("Health server listening")

async def main():
    if not BOT_TOKEN or not ADMIN_ID:
        raise SystemExit("Set BOT_TOKEN and ADMIN_ID environment variables.")
    init_db()
    dp.include_router(r); dp.include_router(adm)
    await run_web()
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
