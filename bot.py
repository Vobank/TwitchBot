# -*- coding: utf-8 -*-
"""
Твич-бот: модерация, команды, таймеры, приветствия.
Настройки — в config.json (или через веб-панель).
Запуск: python bot.py
"""
import os
import re
import sys
import json
import time
import asyncio

import requests
from twitchio.ext import commands

try:  # ровный русский в логах на Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")

def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

CFG = load_config()

LINK_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(ru|com|net|org|io|gg|tv|me|xyz|shop)\b)", re.I)

def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


class Bot(commands.Bot):
    def __init__(self):
        token = CFG["bot_token"]
        if token and not token.startswith("oauth:"):
            token = "oauth:" + token
        super().__init__(token=token, prefix="!",
                         initial_channels=[CFG["channel"].lower().lstrip("#")] if CFG["channel"] else [])
        self.token_raw = CFG["bot_token"].replace("oauth:", "")
        self.client_id = CFG.get("client_id", "")
        self.broadcaster_id = None
        self.bot_id = None
        self.seen = set()            # кто уже писал (для приветствий)
        self.warns = {}              # предупреждения по нарушителям
        self.permits = {}            # временные разрешения на ссылку
        self.msg_count = 0           # сообщений с прошлого таймера

    # ---------- Helix (модерация через API) ----------
    def _headers(self):
        return {"Authorization": f"Bearer {self.token_raw}", "Client-Id": self.client_id}

    async def helix_get_id(self, login):
        def _do():
            r = requests.get(f"https://api.twitch.tv/helix/users?login={login}",
                             headers=self._headers(), timeout=10)
            d = r.json().get("data", [])
            return d[0]["id"] if d else None
        try:
            return await asyncio.to_thread(_do)
        except Exception as e:
            log(f"Helix get_id ошибка: {e}"); return None

    async def timeout_user(self, user_id, seconds, reason=""):
        def _do():
            url = (f"https://api.twitch.tv/helix/moderation/bans?"
                   f"broadcaster_id={self.broadcaster_id}&moderator_id={self.bot_id}")
            body = {"data": {"user_id": str(user_id), "reason": reason[:400]}}
            if seconds:
                body["data"]["duration"] = int(seconds)
            return requests.post(url, headers=self._headers(), json=body, timeout=10)
        try:
            await asyncio.to_thread(_do)
        except Exception as e:
            log(f"timeout ошибка: {e}")

    async def delete_message(self, message_id):
        def _do():
            url = (f"https://api.twitch.tv/helix/moderation/chat?"
                   f"broadcaster_id={self.broadcaster_id}&moderator_id={self.bot_id}&message_id={message_id}")
            return requests.delete(url, headers=self._headers(), timeout=10)
        try:
            await asyncio.to_thread(_do)
        except Exception as e:
            log(f"delete ошибка: {e}")

    # ---------- События ----------
    async def event_ready(self):
        log(f"Бот вошёл как {self.nick}")
        self.bot_id = await self.helix_get_id(self.nick)
        self.broadcaster_id = await self.helix_get_id(CFG["channel"].lower().lstrip("#"))
        log(f"Канал: {CFG['channel']} (id {self.broadcaster_id}), бот id {self.bot_id}")
        if not self.broadcaster_id or not self.bot_id:
            log("⚠ Не удалось получить ID — проверь client_id и токен. Модерация через API не будет работать.")
        self.loop.create_task(self.timer_loop())
        ch = self.get_channel(CFG["channel"].lower().lstrip("#"))
        if ch:
            await ch.send("Бот на связи! 🤖")

    async def event_message(self, message):
        if message.echo:
            return
        author = message.author
        name = (author.name or "").lower()
        is_mod = author.is_mod or author.is_broadcaster

        # 1) Приветствие новичка
        g = CFG.get("greetings", {})
        if g.get("enabled") and name not in self.seen and name not in [x.lower() for x in g.get("ignore", [])]:
            self.seen.add(name)
            try:
                await message.channel.send(g.get("message", "Привет, @{user}!").replace("{user}", author.name))
            except Exception:
                pass
        else:
            self.seen.add(name)

        self.msg_count += 1

        # 2) Модерация (модеров не трогаем)
        if not is_mod:
            if await self.moderate(message):
                return   # сообщение нарушило правила — команды не обрабатываем

        # 3) Команды
        if message.content.startswith("!"):
            await self.handle_command(message)

    # ---------- Модерация ----------
    async def moderate(self, message):
        m = CFG.get("moderation", {})
        text = message.content
        name = (message.author.name or "").lower()
        violation = None

        # запрещённые слова
        if m.get("block_words"):
            low = text.lower()
            for w in m.get("banned_words", []):
                if w and w.lower() in low:
                    violation = "запрещённое слово"; break

        # ссылки
        if not violation and m.get("block_links") and LINK_RE.search(text):
            if self.permits.get(name, 0) > time.time():
                self.permits.pop(name, None)      # разовое разрешение использовано
            else:
                violation = "ссылка"

        # капс
        if not violation and m.get("block_caps"):
            letters = [c for c in text if c.isalpha()]
            if len(letters) >= m.get("caps_min_len", 12):
                caps = sum(1 for c in letters if c.isupper())
                if caps / len(letters) * 100 >= m.get("caps_percent", 70):
                    violation = "капс"

        # спам эмоутами
        if not violation and m.get("max_emotes"):
            emotes = message.tags.get("emotes") if message.tags else None
            if emotes:
                count = sum(part.count(",") + 1 for part in emotes.split("/"))
                if count > m.get("max_emotes", 8):
                    violation = "спам эмоутами"

        if not violation:
            return False

        # действие
        if m.get("delete_message") and message.id:
            await self.delete_message(message.id)
        warns = self.warns.get(name, 0) + 1
        self.warns[name] = warns
        if m.get("warn_first") and warns == 1:
            try:
                await message.channel.send(f"@{message.author.name}, предупреждение: {violation}. Дальше — тайм-аут.")
            except Exception:
                pass
        else:
            await self.timeout_user(message.author.id, m.get("timeout_seconds", 60), violation)
            log(f"Тайм-аут {name} за {violation}")
        return True

    # ---------- Команды ----------
    async def handle_command(self, message):
        parts = message.content[1:].split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]
        ch = message.channel
        is_mod = message.author.is_mod or message.author.is_broadcaster

        # встроенные
        if cmd in ("команды", "commands", "help"):
            names = ", ".join("!" + c for c in CFG.get("commands", {}))
            await ch.send(f"Команды: {names or 'пока нет'}")
            return
        if cmd in ("аптайм", "uptime"):
            await ch.send(await self.get_uptime())
            return

        # модерские
        if is_mod:
            if cmd in ("addcom", "добавь") and len(args) >= 2:
                CFG["commands"][args[0].lstrip("!").lower()] = " ".join(args[1:]); save_config(CFG)
                await ch.send(f"Команда !{args[0].lstrip('!')} добавлена."); return
            if cmd in ("delcom", "удали") and args:
                CFG["commands"].pop(args[0].lstrip("!").lower(), None); save_config(CFG)
                await ch.send(f"Команда !{args[0].lstrip('!')} удалена."); return
            if cmd == "permit" and args:
                self.permits[args[0].lstrip("@").lower()] = time.time() + 60
                await ch.send(f"@{args[0].lstrip('@')} — можно кинуть ссылку (60 сек)."); return
            if cmd in ("бан", "ban") and args:
                uid = await self.helix_get_id(args[0].lstrip("@").lower())
                if uid: await self.timeout_user(uid, 0, "бан модератором"); await ch.send(f"Забанен {args[0]}.")
                return
            if cmd in ("мут", "timeout") and args:
                secs = int(args[1]) if len(args) > 1 and args[1].isdigit() else 300
                uid = await self.helix_get_id(args[0].lstrip("@").lower())
                if uid: await self.timeout_user(uid, secs, "мут модератором"); await ch.send(f"Тайм-аут {args[0]} на {secs} сек.")
                return

        # пользовательские
        if cmd in CFG.get("commands", {}):
            text = CFG["commands"][cmd].replace("{user}", message.author.name)
            await ch.send(text)

    async def get_uptime(self):
        def _do():
            r = requests.get(f"https://api.twitch.tv/helix/streams?user_id={self.broadcaster_id}",
                             headers=self._headers(), timeout=10)
            return r.json().get("data", [])
        try:
            d = await asyncio.to_thread(_do)
            if not d:
                return "Стрим сейчас не идёт."
            started = d[0]["started_at"]
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            secs = int((datetime.now(timezone.utc) - dt).total_seconds())
            h, m = secs // 3600, (secs % 3600) // 60
            return f"Стрим идёт уже {h} ч {m} мин."
        except Exception:
            return "Не смог узнать аптайм."

    # ---------- Таймеры ----------
    async def timer_loop(self):
        idx = 0
        while True:
            t = CFG.get("timers", {})
            interval = max(1, t.get("interval_min", 10)) * 60
            await asyncio.sleep(interval)
            t = CFG.get("timers", {})            # перечитываем (вдруг поменяли в панели)
            if not t.get("enabled") or not t.get("messages"):
                continue
            if self.msg_count < t.get("min_messages", 0):
                continue
            self.msg_count = 0
            ch = self.get_channel(CFG["channel"].lower().lstrip("#"))
            if ch:
                msgs = t["messages"]
                try:
                    await ch.send(msgs[idx % len(msgs)]); idx += 1
                except Exception:
                    pass


if __name__ == "__main__":
    CFG = load_config()
    if not CFG.get("channel") or not CFG.get("bot_token"):
        print("=" * 50)
        print("  Не заполнен config.json (channel / bot_token).")
        print("  Открой панель управления или впиши данные в config.json.")
        print("=" * 50)
        input("Enter для выхода...")
    else:
        print("Запускаю твич-бота...", flush=True)
        Bot().run()
