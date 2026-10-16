# -*- coding: utf-8 -*-
"""
Веб-панель управления твич-ботом.
Открывается на http://127.0.0.1:5005
Позволяет: вписать данные канала/токена, настроить модерацию,
команды, таймеры, приветствия, запустить/остановить бота, видеть логи.
"""
import os
import sys
import json
import subprocess
import threading
import collections

from flask import Flask, request, jsonify, render_template_string

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
PYTHON = sys.executable

app = Flask(__name__)

bot_proc = None
log_lines = collections.deque(maxlen=400)


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _reader(proc):
    for line in iter(proc.stdout.readline, ""):
        if line:
            log_lines.append(line.rstrip("\n"))
    log_lines.append("— бот остановлен —")


def start_bot():
    global bot_proc
    if bot_proc and bot_proc.poll() is None:
        return False
    log_lines.clear()
    log_lines.append("Запускаю бота...")
    bot_proc = subprocess.Popen(
        [PYTHON, os.path.join(BASE, "bot.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=BASE, text=True, encoding="utf-8", errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    threading.Thread(target=_reader, args=(bot_proc,), daemon=True).start()
    return True


def stop_bot():
    global bot_proc
    if bot_proc and bot_proc.poll() is None:
        bot_proc.terminate()
        try:
            bot_proc.wait(timeout=5)
        except Exception:
            bot_proc.kill()
        return True
    return False


def bot_running():
    return bot_proc is not None and bot_proc.poll() is None


PAGE = r"""
<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Твич-бот · Панель</title>
<style>
:root{--bg:#0f0f13;--card:#1b1b24;--line:#2c2c3a;--txt:#e9e9f0;--mut:#9a9ab0;
--pri:#9146ff;--pri2:#7a2ff2;--ok:#28c76f;--bad:#ff4d6d;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:Segoe UI,system-ui,sans-serif;font-size:15px}
.wrap{max-width:860px;margin:0 auto;padding:18px}
h1{font-size:22px;margin:0 0 4px;display:flex;align-items:center;gap:10px}
h2{font-size:16px;margin:0 0 12px;color:var(--pri)}
.sub{color:var(--mut);margin:0 0 18px;font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:18px;margin-bottom:16px}
label{display:block;font-size:13px;color:var(--mut);margin:10px 0 4px}
input[type=text],input[type=password],input[type=number],textarea{
width:100%;background:#12121a;border:1px solid var(--line);color:var(--txt);
border-radius:9px;padding:9px 11px;font-size:14px;font-family:inherit}
textarea{min-height:72px;resize:vertical}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>div{flex:1;min-width:140px}
.sw{display:flex;align-items:center;gap:10px;margin:8px 0;cursor:pointer}
.sw input{width:42px;height:24px;appearance:none;background:var(--line);
border-radius:12px;position:relative;cursor:pointer;transition:.2s;flex:none}
.sw input:checked{background:var(--pri)}
.sw input::after{content:"";position:absolute;width:18px;height:18px;border-radius:50%;
background:#fff;top:3px;left:3px;transition:.2s}
.sw input:checked::after{left:21px}
.btn{background:var(--pri);color:#fff;border:0;border-radius:10px;padding:11px 20px;
font-size:15px;font-weight:600;cursor:pointer}
.btn:hover{background:var(--pri2)}
.btn.g{background:#2c2c3a}.btn.g:hover{background:#3a3a4c}
.btn.r{background:var(--bad)}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dot{width:11px;height:11px;border-radius:50%;background:var(--bad)}
.dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
#log{background:#08080c;border:1px solid var(--line);border-radius:10px;padding:12px;
height:240px;overflow:auto;font-family:Consolas,monospace;font-size:12.5px;
white-space:pre-wrap;color:#c8c8d8}
.hint{font-size:12px;color:var(--mut);margin-top:6px;line-height:1.5}
.hint a{color:var(--pri)}
.tag{display:inline-block;background:#12121a;border:1px solid var(--line);
border-radius:6px;padding:2px 7px;font-size:12px;margin:2px}
.saved{color:var(--ok);font-size:13px;margin-left:8px;opacity:0;transition:.3s}
.saved.show{opacity:1}
</style></head><body><div class="wrap">
<h1>🟣 Твич-бот <span id="dot" class="dot"></span></h1>
<p class="sub">Модерация · команды · таймеры · приветствия</p>

<div class="card">
<h2>Запуск</h2>
<div class="bar">
<button class="btn" onclick="ctl('start')">▶ Запустить бота</button>
<button class="btn r" onclick="ctl('stop')">⏹ Остановить</button>
<span id="status" style="color:var(--mut)"></span>
</div>
</div>

<div class="card">
<h2>Подключение к Твичу</h2>
<label>Название твоего канала (ник на Twitch)</label>
<input type="text" id="channel" placeholder="mychannel">
<label>Ник бот-аккаунта (можно тот же канал)</label>
<input type="text" id="bot_username" placeholder="mybot">
<label>OAuth-токен бота</label>
<input type="password" id="bot_token" placeholder="oauth:xxxxxxxx">
<label>Client ID</label>
<input type="password" id="client_id" placeholder="xxxxxxxxxxxx">
<div class="hint">
Токен и Client ID возьми на <a href="https://twitchtokengenerator.com" target="_blank">twitchtokengenerator.com</a>
(нужны права: chat:read, chat:edit, moderator:manage:banned_users, moderator:manage:chat_messages).
Бот-аккаунт должен быть <b>модератором</b> твоего канала (в чате: <span class="tag">/mod никбота</span>).
</div>
</div>

<div class="card">
<h2>Модерация</h2>
<label class="sw"><input type="checkbox" id="m_links"> Блокировать ссылки</label>
<label class="sw"><input type="checkbox" id="m_caps"> Блокировать КАПС</label>
<div class="row">
<div><label>Порог капса, %</label><input type="number" id="caps_percent"></div>
<div><label>Мин. длина для капса</label><input type="number" id="caps_min_len"></div>
</div>
<label class="sw"><input type="checkbox" id="m_words"> Блокировать запрещённые слова</label>
<label>Запрещённые слова (через запятую)</label>
<textarea id="banned_words"></textarea>
<div class="row">
<div><label>Макс. эмоутов в сообщении</label><input type="number" id="max_emotes"></div>
<div><label>Тайм-аут, сек</label><input type="number" id="timeout_seconds"></div>
</div>
<label class="sw"><input type="checkbox" id="warn_first"> Сначала предупреждать, потом тайм-аут</label>
<label class="sw"><input type="checkbox" id="delete_message"> Удалять сообщение-нарушение</label>
</div>

<div class="card">
<h2>Команды чата</h2>
<div class="hint">Формат: <span class="tag">имя = текст ответа</span>, каждая с новой строки. Зрители вызывают через <b>!имя</b>. Можно <span class="tag">{user}</span> — подставит ник.</div>
<textarea id="commands" style="min-height:120px"></textarea>
<div class="hint">Модеры прямо в чате: <span class="tag">!addcom имя текст</span> · <span class="tag">!delcom имя</span> · <span class="tag">!бан @ник</span> · <span class="tag">!мут @ник 300</span> · <span class="tag">!permit @ник</span> (разово разрешить ссылку). Встроенные: <span class="tag">!команды</span> <span class="tag">!аптайм</span></div>
</div>

<div class="card">
<h2>Таймеры (автосообщения)</h2>
<label class="sw"><input type="checkbox" id="t_enabled"> Включить таймеры</label>
<div class="row">
<div><label>Интервал, мин</label><input type="number" id="t_interval"></div>
<div><label>Мин. сообщений в чате между таймерами</label><input type="number" id="t_minmsg"></div>
</div>
<label>Сообщения (каждое с новой строки, крутятся по кругу)</label>
<textarea id="t_messages" style="min-height:90px"></textarea>
</div>

<div class="card">
<h2>Приветствия</h2>
<label class="sw"><input type="checkbox" id="g_enabled"> Приветствовать новых зрителей</label>
<label>Текст приветствия ({user} — ник)</label>
<input type="text" id="g_message">
<label>Не приветствовать (боты, через запятую)</label>
<input type="text" id="g_ignore">
</div>

<div class="card">
<div class="bar">
<button class="btn" onclick="saveAll()">💾 Сохранить настройки</button>
<span id="saved" class="saved">Сохранено ✓</span>
</div>
<div class="hint">После сохранения при работающем боте — нажми «Остановить» и «Запустить», чтобы применить подключение. Команды/таймеры/приветствия подхватываются на лету.</div>
</div>

<div class="card">
<h2>Логи бота</h2>
<div id="log"></div>
</div>

</div>
<script>
const $=id=>document.getElementById(id);
function fill(c){
 $('channel').value=c.channel||'';$('bot_username').value=c.bot_username||'';
 $('bot_token').value=c.bot_token||'';$('client_id').value=c.client_id||'';
 const m=c.moderation||{};
 $('m_links').checked=!!m.block_links;$('m_caps').checked=!!m.block_caps;
 $('caps_percent').value=m.caps_percent??70;$('caps_min_len').value=m.caps_min_len??12;
 $('m_words').checked=!!m.block_words;$('banned_words').value=(m.banned_words||[]).join(', ');
 $('max_emotes').value=m.max_emotes??8;$('timeout_seconds').value=m.timeout_seconds??60;
 $('warn_first').checked=!!m.warn_first;$('delete_message').checked=!!m.delete_message;
 const cm=c.commands||{};
 $('commands').value=Object.entries(cm).map(([k,v])=>k+' = '+v).join('\n');
 const t=c.timers||{};
 $('t_enabled').checked=!!t.enabled;$('t_interval').value=t.interval_min??10;
 $('t_minmsg').value=t.min_messages??5;$('t_messages').value=(t.messages||[]).join('\n');
 const g=c.greetings||{};
 $('g_enabled').checked=!!g.enabled;$('g_message').value=g.message||'';
 $('g_ignore').value=(g.ignore||[]).join(', ');
}
function collect(){
 const cmds={};
 $('commands').value.split('\n').forEach(l=>{
  const i=l.indexOf('=');if(i>0){const k=l.slice(0,i).trim().replace(/^!/,'').toLowerCase();
  const v=l.slice(i+1).trim();if(k)cmds[k]=v;}});
 return {
  channel:$('channel').value.trim(),bot_username:$('bot_username').value.trim(),
  bot_token:$('bot_token').value.trim(),client_id:$('client_id').value.trim(),
  moderation:{block_links:$('m_links').checked,block_caps:$('m_caps').checked,
   caps_percent:+$('caps_percent').value,caps_min_len:+$('caps_min_len').value,
   block_words:$('m_words').checked,
   banned_words:$('banned_words').value.split(',').map(s=>s.trim()).filter(Boolean),
   max_emotes:+$('max_emotes').value,timeout_seconds:+$('timeout_seconds').value,
   warn_first:$('warn_first').checked,delete_message:$('delete_message').checked},
  commands:cmds,
  timers:{enabled:$('t_enabled').checked,interval_min:+$('t_interval').value,
   min_messages:+$('t_minmsg').value,
   messages:$('t_messages').value.split('\n').map(s=>s.trim()).filter(Boolean)},
  greetings:{enabled:$('g_enabled').checked,message:$('g_message').value,
   ignore:$('g_ignore').value.split(',').map(s=>s.trim()).filter(Boolean)}
 };
}
async function saveAll(){
 await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(collect())});
 const s=$('saved');s.classList.add('show');setTimeout(()=>s.classList.remove('show'),1500);
}
async function ctl(a){await fetch('/'+a,{method:'POST'});setTimeout(poll,400);}
async function poll(){
 const r=await fetch('/state');const d=await r.json();
 $('dot').className='dot'+(d.running?' on':'');
 $('status').textContent=d.running?'● работает':'○ остановлен';
 $('log').textContent=d.log.join('\n');$('log').scrollTop=1e9;
}
fetch('/config').then(r=>r.json()).then(fill);
setInterval(poll,1500);poll();
</script></body></html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)

@app.route("/config")
def get_config():
    return jsonify(load_config())

@app.route("/save", methods=["POST"])
def save():
    cfg = request.get_json(force=True)
    save_config(cfg)
    return jsonify(ok=True)

@app.route("/start", methods=["POST"])
def r_start():
    return jsonify(ok=start_bot())

@app.route("/stop", methods=["POST"])
def r_stop():
    return jsonify(ok=stop_bot())

@app.route("/state")
def state():
    return jsonify(running=bot_running(), log=list(log_lines))


if __name__ == "__main__":
    import webbrowser
    print("Панель управления: http://127.0.0.1:5005", flush=True)
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5005")).start()
    app.run(host="127.0.0.1", port=5005, threaded=True)
