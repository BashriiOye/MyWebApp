import re, os, json, time, subprocess, requests, tempfile, asyncio, threading
from flask import Flask, request, jsonify, send_from_directory, Response

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, static_folder=None)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_termux(cmd_list, timeout=10):
    if isinstance(cmd_list, str): cmd_list = cmd_list.split()
    try:
        r = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e: return "", str(e), 1

def get_web_context(query):
    import urllib.parse
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            snippets = re.findall(r'class="result__snippet">(.*?)</a>', r.text, re.DOTALL)
            if snippets:
                clean = [re.sub('<[^<]+?>', '', s).strip() for s in snippets[:5]]
                return " | ".join(clean)
    except: pass
    return ""

@app.after_request
def no_cache(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route("/")
def index(): return send_from_directory(BASE_DIR, "index.html")

@app.route("/api/models")
def list_models():
    return jsonify({"models": [
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B (Fast)", "provider": "Groq"},
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B (Smart)", "provider": "Groq"},
        {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "provider": "Groq"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "provider": "Groq"},
        {"id": "gemma2-9b-it", "name": "Gemma 2 9B", "provider": "Groq"}
    ]})

@app.route("/api/voices")
def list_voices():
    return jsonify([
        {"id": "ananya", "name": "Ananya", "flag": "🇮🇳", "desc": "Sweet Indian teen"},
        {"id": "swara", "name": "Swara", "flag": "🇮🇳", "desc": "Soft Indian teen"},
        {"id": "neerja", "name": "Neerja", "flag": "🇮🇳", "desc": "Indian English"},
        {"id": "aarohi", "name": "Aarohi", "flag": "🇮🇳", "desc": "Marathi girl"},
        {"id": "tanishaa", "name": "Tanishaa", "flag": "🇮🇳", "desc": "Bengali girl"},
        {"id": "pallavi", "name": "Pallavi", "flag": "🇮🇳", "desc": "Tamil girl"},
        {"id": "shruti", "name": "Shruti", "flag": "🇮🇳", "desc": "Telugu girl"},
        {"id": "uzma", "name": "Uzma", "flag": "🇵🇰", "desc": "Pakistani Urdu"},
        {"id": "asad", "name": "Asad", "flag": "🇵🇰", "desc": "Pakistani male"}
    ])

VOICE_DB = {
    "ananya": {"voice": "hi-IN-AnanyaNeural", "rate": "+12%", "pitch": "+18Hz"},
    "swara": {"voice": "hi-IN-SwaraNeural", "rate": "+10%", "pitch": "+15Hz"},
    "neerja": {"voice": "en-IN-NeerjaNeural", "rate": "+12%", "pitch": "+18Hz"},
    "aarohi": {"voice": "mr-IN-AarohiNeural", "rate": "+12%", "pitch": "+18Hz"},
    "tanishaa": {"voice": "bn-IN-TanishaaNeural", "rate": "+12%", "pitch": "+18Hz"},
    "pallavi": {"voice": "ta-IN-PallaviNeural", "rate": "+12%", "pitch": "+18Hz"},
    "shruti": {"voice": "te-IN-ShrutiNeural", "rate": "+12%", "pitch": "+18Hz"},
    "uzma": {"voice": "ur-PK-UzmaNeural", "rate": "+12%", "pitch": "+18Hz"},
    "asad": {"voice": "ur-PK-AsadNeural", "rate": "+10%", "pitch": "+5Hz"},
    "default": {"voice": "hi-IN-AnanyaNeural", "rate": "+12%", "pitch": "+18Hz"}
}

@app.route("/speak")
def speak():
    text = (request.args.get("text") or "").strip()
    voice_key = (request.args.get("voice") or "default").strip().lower()
    rate = (request.args.get("rate") or "+12%").strip()
    pitch = (request.args.get("pitch") or "+18Hz").strip()
    if not text: return jsonify({"error": "no text"}), 400
    config = VOICE_DB.get(voice_key, VOICE_DB["default"])
    try:
        import edge_tts
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3"); tmp.close()
        async def _gen():
            c = edge_tts.Communicate(text, config["voice"], rate=rate, pitch=pitch)
            await c.save(tmp.name)
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        loop.run_until_complete(_gen()); loop.close()
        with open(tmp.name, "rb") as f: audio = f.read()
        os.unlink(tmp.name)
        return Response(audio, mimetype="audio/mpeg")
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS": return jsonify({"ok": True})
    try:
        data = request.get_json(force=True, silent=True) or {}
        msg, key = (data.get("message") or "").strip(), (data.get("api_key") or "").strip()
        model = data.get("model", "openai/gpt-oss-120b")
        temp = float(data.get("temperature", 0.7))
        max_tokens = int(data.get("max_tokens", 2048))
        sys_prompt = data.get("system_prompt", "You are Mano, AI by Bashrii Oye. Be helpful and friendly.")
        think = bool(data.get("think", False))
        web = bool(data.get("web_search", False))
        
        if not msg: return jsonify({"reply": "Type a message."})
        if not key: return jsonify({"reply": "Add Groq API key in Settings."})
        
        context = ""
        if web:
            ctx = get_web_context(msg)
            if ctx: context = f"\n\nWeb Context:\n{ctx}"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt + context},
                {"role": "user", "content": msg}
            ],
            "temperature": temp,
            "max_tokens": max_tokens
        }
        
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json=payload, timeout=30)
        if r.status_code == 200:
            return jsonify({"reply": r.json()["choices"][0]["message"]["content"].strip()})
        return jsonify({"reply": f"Error {r.status_code}: {r.text[:100]}"})
    except Exception as e: return jsonify({"reply": f"Error: {str(e)[:100]}"})

@app.route("/api/notes", methods=["GET", "POST", "DELETE"])
def notes_api():
    NOTES_FILE = os.path.join(BASE_DIR, "notes.json")
    def load():
        if os.path.exists(NOTES_FILE):
            try:
                with open(NOTES_FILE) as f: return json.load(f)
            except: return []
        return []
    def save(d):
        with open(NOTES_FILE, "w") as f: json.dump(d, f)
    if request.method == "GET": return jsonify(load())
    if request.method == "POST":
        d = request.get_json() or {}
        items = load()
        items.append({"id": int(time.time()), "text": d.get("text", ""), "date": time.strftime("%Y-%m-%d %H:%M")})
        save(items); return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        save([i for i in load() if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

@app.route("/api/reminders", methods=["GET", "POST", "DELETE"])
def reminders_api():
    REM_FILE = os.path.join(BASE_DIR, "reminders.json")
    def load():
        if os.path.exists(REM_FILE):
            try:
                with open(REM_FILE) as f: return json.load(f)
            except: return []
        return []
    def save(d):
        with open(REM_FILE, "w") as f: json.dump(d, f)
    if request.method == "GET": return jsonify(load())
    if request.method == "POST":
        d = request.get_json() or {}
        items = load()
        items.append({"id": int(time.time()), "text": d.get("text", ""), "done": False})
        save(items); return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        save([i for i in load() if i.get("id") != d.get("id")])
        return jsonify({"ok": True})


# ─── MAYA FEATURES START ───

MOOD_FILE = os.path.join(BASE_DIR, "mood.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "journal.json")
MEMORIES_FILE = os.path.join(BASE_DIR, "memories.json")

def _load(fp):
    if os.path.exists(fp):
        try:
            with open(fp, 'r') as f: return json.load(f)
        except: return []
    return []

def _save(fp, d):
    with open(fp, 'w') as f: json.dump(d, f, indent=2)

@app.route("/api/mood", methods=["GET", "POST"])
def mood_api():
    if request.method == "GET": return jsonify(_load(MOOD_FILE))
    d = request.get_json() or {}
    items = _load(MOOD_FILE)
    items.append({"id": int(time.time()), "mood": d.get("mood", ""), "note": d.get("note", ""), "date": time.strftime("%Y-%m-%d %H:%M")})
    _save(MOOD_FILE, items)
    return jsonify({"ok": True, "items": items})

@app.route("/api/journal", methods=["GET", "POST", "DELETE"])
def journal_api():
    if request.method == "GET": return jsonify(_load(JOURNAL_FILE))
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(JOURNAL_FILE)
        items.append({"id": int(time.time()), "title": d.get("title", ""), "text": d.get("text", ""), "mood": d.get("mood", "neutral"), "date": time.strftime("%Y-%m-%d %H:%M")})
        _save(JOURNAL_FILE, items)
        return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(JOURNAL_FILE, [i for i in _load(JOURNAL_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

@app.route("/api/memories", methods=["GET", "POST", "DELETE"])
def memories_api():
    if request.method == "GET": return jsonify(_load(MEMORIES_FILE))
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(MEMORIES_FILE)
        items.append({"id": int(time.time()), "text": d.get("text", ""), "category": d.get("category", "general"), "date": time.strftime("%Y-%m-%d %H:%M")})
        _save(MEMORIES_FILE, items)
        return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(MEMORIES_FILE, [i for i in _load(MEMORIES_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

@app.route("/api/energy")
def energy_api():
    """Unlimited energy — no license, no limits. FREE FOREVER."""
    return jsonify({"energy": 999, "max": 999, "unlimited": True, "premium": True, "license": "FREE_UNLOCKED"})

@app.route("/api/scan", methods=["POST"])
def scan_api():
    """Simple scan endpoint. Accepts base64 image and returns a friendly message."""
    try:
        d = request.get_json() or {}
        img = d.get("image", "")
        if not img: return jsonify({"ok": False, "error": "No image"})
        return jsonify({"ok": True, "result": "Scan received! Use Mano Chat to describe what you see.", "size_kb": round(len(img)/1024, 1)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/dashboard")
def dashboard_api():
    """Returns all home dashboard data in one call."""
    return jsonify({
        "energy": {"current": 999, "max": 999, "unlimited": True},
        "premium": {"unlocked": True, "plan": "FREE FOREVER"},
        "mood": (_load(MOOD_FILE) or [{"mood": "warm", "note": "All good"}])[-1],
        "journal_count": len(_load(JOURNAL_FILE)),
        "memories_count": len(_load(MEMORIES_FILE)),
        "weather": {"temp": "--", "desc": "Loading"},
        "date": time.strftime("%A, %d %b %Y")
    })

# ─── MAYA FEATURES END ───


# ─── BACKUP ENDPOINTS START ───
import shutil

@app.route("/api/backup/export")
def backup_export():
    """Export all Mano data as JSON."""
    data = {}
    for f in ["notes.json", "reminders.json", "mood.json", "journal.json", "memories.json"]:
        fp = os.path.join(BASE_DIR, f)
        if os.path.exists(fp):
            try:
                with open(fp, 'r') as fh: data[f] = json.load(fh)
            except: data[f] = []
    return jsonify({"ok": True, "data": data, "exported_at": time.strftime("%Y-%m-%d %H:%M")})

@app.route("/api/backup/import", methods=["POST"])
def backup_import():
    """Import Mano data from JSON."""
    try:
        payload = request.get_json() or {}
        data = payload.get("data", {})
        for fname, items in data.items():
            fp = os.path.join(BASE_DIR, fname)
            with open(fp, 'w') as fh: json.dump(items, fh, indent=2)
        return jsonify({"ok": True, "message": "Backup restored successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
# ─── BACKUP ENDPOINTS END ───


# ═══ ALL_FEATURES_START ═══

# ─── STREAMING ENDPOINTS ───
@app.route("/api/youtube-search")
def youtube_search():
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"error": "No query"}), 400
    return jsonify({"ok": True, "url": f"https://www.youtube.com/results?search_query={q}"})

@app.route("/api/where-to-watch")
def where_to_watch():
    title = request.args.get("title", "").strip()
    if not title: return jsonify({"error": "No title"}), 400
    return jsonify({"ok": True, "url": f"https://www.justwatch.com/pk/search?q={title}", "title": title})

@app.route("/api/drama-search")
def drama_search():
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"error": "No query"}), 400
    results = []
    try:
        r = requests.get(f"https://api.tvmaze.com/search/shows?q={q}", timeout=10)
        if r.status_code == 200:
            for item in r.json()[:5]:
                s = item.get("show", {})
                results.append({
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "premiered": s.get("premiered"),
                    "genres": s.get("genres"),
                    "rating": (s.get("rating") or {}).get("average"),
                    "network": ((s.get("network") or {}).get("name")) or "N/A",
                    "source": "TVMaze"
                })
    except Exception as e:
        print(f"TVMaze error: {e}")
    return jsonify({"ok": True, "results": results})

@app.route("/api/free-ai", methods=["POST", "OPTIONS"])
def free_ai():
    if request.method == "OPTIONS": return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg: return jsonify({"reply": "No message"}), 400
    
    # Try Pollinations
    try:
        r = requests.post("https://text.pollinations.ai/openai", json={
            "model": "openai",
            "messages": [{"role": "user", "content": msg}]
        }, timeout=20)
        if r.status_code == 200:
            return jsonify({"reply": r.json()["choices"][0]["message"]["content"], "provider": "Pollinations"})
    except Exception as e:
        print(f"Pollinations failed: {e}")
    
    # Try FreeLlama
    try:
        r = requests.get(f"https://api.freellama.org/v1/chat/completions?prompt={msg}", timeout=20)
        if r.status_code == 200:
            return jsonify({"reply": r.json()["choices"][0]["message"]["content"], "provider": "FreeLlama"})
    except Exception as e:
        print(f"FreeLlama failed: {e}")
    
    return jsonify({"reply": "All free AI providers failed."})

# ─── UTILITY APIs ───
@app.route("/api/crypto")
def crypto_api():
    coin = request.args.get("coin", "bitcoin")
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd,pkr", timeout=10)
        return jsonify(r.json())
    except: return jsonify({"error": "Failed"})

@app.route("/api/dictionary")
def dict_api():
    word = request.args.get("word", "").strip()
    if not word: return jsonify({"error": "No word"}), 400
    try:
        r = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
        return jsonify(r.json())
    except: return jsonify({"error": "Failed"})

@app.route("/api/ip-info")
def ip_info():
    ip = request.args.get("ip", "")
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        return jsonify(r.json())
    except: return jsonify({"error": "Failed"})

@app.route("/api/qr")
def qr_api():
    data = request.args.get("data", "Hello")
    return jsonify({"url": f"https://api.qrserver.com/v1/create-qr-code/?data={data}&size=200x200"})

@app.route("/api/holidays")
def holidays_api():
    year = request.args.get("year", "2025")
    country = request.args.get("country", "PK")
    try:
        r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}", timeout=10)
        return jsonify(r.json())
    except: return jsonify([])

@app.route("/api/iss")
def iss_api():
    try:
        r = requests.get("http://api.open-notify.org/iss-now.json", timeout=10)
        return jsonify(r.json())
    except: return jsonify({"error": "Failed"})

# ─── CAPABILITIES / SYSTEM INFO ───
@app.route("/capabilities")
def capabilities():
    return jsonify({
        "works": [
            {"name": "Web Search", "status": "ok"},
            {"name": "Notes & Reminders", "status": "ok"},
            {"name": "Weather", "status": "ok"},
            {"name": "App Launcher", "status": "ok"},
            {"name": "Voice Output", "status": "ok"},
        ],
        "needs_setup": [
            {"name": "Contacts & SMS", "how": "Install Termux:API"},
            {"name": "Tap buttons in apps", "how": "Install AutoInput + Tasker"},
        ],
        "not_possible": [
            {"name": "Auto-unlock with PIN", "why": "Requires root"},
            {"name": "Silent SMS send", "why": "Android blocks"},
            {"name": "Watch your screen", "why": "Sandbox"},
            {"name": "Always-listening background", "why": "Battery + privacy"},
        ]
    })

# ─── SETUP GUIDES ───
@app.route("/api/setup-guides")
def setup_guides():
    return jsonify([
        {"title": "AutoInput & Tasker", "steps": ["Install AutoInput from Play Store", "Install Tasker", "Grant AutoInput Accessibility permission", "Create task: AutoInput Action"]},
        {"title": "Contacts & SMS (Termux:API)", "steps": ["Install Termux:API APK", "Open it once", "Run: termux-contact-list", "Grant permission when asked"]},
        {"title": "Auto-Unlock (Root)", "steps": ["Root your device", "Install AutoInput", "Set up swipe pattern automation"]}
    ])

# ─── BACKUP/RESTORE ───
# ═══ ALL_FEATURES_END ═══


# ─── LIVE TV ENDPOINTS ───
IPTV_CACHE = {"data": {}, "ts": 0}

@app.route("/api/iptv-channels")
def iptv_channels():
    country = request.args.get("country", "pk").lower()
    now = time.time()
    # Cache for 30 minutes
    if IPTV_CACHE["data"].get(country) and (now - IPTV_CACHE["ts"]) < 1800:
        return jsonify(IPTV_CACHE["data"][country])
    try:
        # Fetch channels
        r = requests.get("https://iptv-org.github.io/api/channels.json", timeout=20)
        if r.status_code != 200:
            return jsonify({"ok": False, "error": "Failed to fetch channels"})
        channels = [c for c in r.json() if (c.get("country") or "").lower() == country]

        # Fetch streams
        s = requests.get("https://iptv-org.github.io/api/streams.json", timeout=20)
        streams = {}
        if s.status_code == 200:
            for st in s.json():
                cid = st.get("channel")
                if cid and st.get("url"):
                    # Prefer m3u8 streams
                    if cid not in streams or ".m3u8" in st.get("url",""):
                        streams[cid] = st.get("url")

        # Merge channels with streams
        result = []
        for c in channels:
            cid = c.get("id")
            if cid in streams:
                # Pick logo
                logo = ""
                if c.get("logo"): logo = c["logo"]
                result.append({
                    "id": cid,
                    "name": c.get("name") or cid,
                    "logo": logo,
                    "stream": streams[cid],
                    "categories": c.get("categories") or []
                })

        # Sort alphabetically
        result.sort(key=lambda x: x["name"].lower())

        payload = {"ok": True, "country": country, "channels": result[:100], "count": len(result)}
        IPTV_CACHE["data"][country] = payload
        IPTV_CACHE["ts"] = now
        return jsonify(payload)
    except Exception as e:
        print(f"IPTV error: {e}")
        return jsonify({"ok": False, "error": str(e), "channels": []})

@app.route("/api/open-vlc")
def open_vlc():
    """Open a stream URL in VLC or default player"""
    url = request.args.get("url", "").strip()
    if not url: return jsonify({"error": "No URL"}), 400
    # Try VLC first, then generic intent
    try:
        subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-t", "video/*"],
                       capture_output=True, timeout=5)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


















# ─── LIVE TV START ───
import json as _json
import time as _time

# Indian Premium Channels — Many backup streams
# Server will auto-test each stream and return the best one
CURATED_CHANNELS = [
    # ══ PAKISTAN ══
    {"id":"geo-news","name":"Geo News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://jk3lz82elw79-hls-live.5centscdn.com/geo/83ccf718ec6040646c295cb25dbef052.sdp/playlist.m3u8",
        "http://109.232.227.38:8000/live/soot3/93retno/566.ts"
    ]},
    {"id":"ary-news","name":"ARY News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.arynews.tv/hls/arynews.m3u8"
    ]},
    {"id":"hum-tv","name":"Hum TV","country":"PK","cat":"Entertainment","icon":"🇵🇰","streams":[
        "https://live.hum.tv/hls/humtv.m3u8",
        "http://109.232.227.38:8000/live/soot3/93retno/568.ts"
    ]},
    {"id":"ary-digital","name":"ARY Digital","country":"PK","cat":"Entertainment","icon":"🇵🇰","streams":[
        "https://live.arydigital.tv/hls/arydigital.m3u8",
        "http://109.232.227.38:8000/live/soot3/93retno/564.ts"
    ]},
    {"id":"green-tv","name":"Green TV","country":"PK","cat":"Entertainment","icon":"🌿","streams":[
        "http://cdn01.palki.tv/live/GreenTV-M/index.fmp4.m3u8"
    ]},
    {"id":"samaa","name":"Samaa TV","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.samaa.tv/hls/samaa.m3u8"
    ]},
    {"id":"dunya","name":"Dunya News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.dunyanews.tv/hls/dunya.m3u8"
    ]},
    {"id":"express","name":"Express News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.express.pk/hls/expressnews.m3u8"
    ]},
    {"id":"92news","name":"92 News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.92newshd.tv/hls/92news.m3u8"
    ]},
    {"id":"bol-news","name":"BOL News","country":"PK","cat":"News","icon":"🇵🇰","streams":[
        "https://live.bolnews.com/hls/bolnews.m3u8"
    ]},
    {"id":"ptv-sports","name":"PTV Sports","country":"PK","cat":"Sports","icon":"⚽","streams":[
        "https://live.ptvsports.pk/hls/ptvsports.m3u8"
    ]},
    {"id":"ten-sports","name":"Ten Sports","country":"PK","cat":"Sports","icon":"⚽","streams":[
        "https://live.tensports.pk/hls/tensports.m3u8"
    ]},

    # ══ INDIA — PREMIUM ══
    {"id":"star-plus","name":"Star Plus","country":"IN","cat":"Entertainment","icon":"⭐","streams":[
        "http://103.72.179.30:1935/GECHindi/STAR_PLUS.stream_720p/Playlist.m3u8",
        "http://bapatv.live:8080/starplus/index.m3u8",
        "http://144.217.70.181:9587/hin2/STARPLUSHD/index.m3u8?token=test",
        "http://198.255.94.194:8080/live/starplus/index.m3u8",
        "http://185.22.154.234:8880/live/starplus/playlist.m3u8"
    ]},
    {"id":"colors","name":"Colors TV","country":"IN","cat":"Entertainment","icon":"🌈","streams":[
        "http://103.72.179.30:1935/GECHindi/COLORS.stream_720p/Playlist.m3u8",
        "http://bapatv.live:8080/colorshd/index.m3u8",
        "http://198.255.94.194:8080/live/colors/index.m3u8",
        "http://185.22.154.234:8880/live/colorshd/playlist.m3u8"
    ]},
    {"id":"sony","name":"Sony TV","country":"IN","cat":"Entertainment","icon":"🎬","streams":[
        "http://103.72.179.30:1935/GECHindi/SONY.stream_720p/Playlist.m3u8",
        "http://bapatv.live:8080/sonyhd/index.m3u8",
        "http://198.255.94.194:8080/live/sony/index.m3u8"
    ]},
    {"id":"zee-tv","name":"Zee TV","country":"IN","cat":"Entertainment","icon":"🎭","streams":[
        "https://y5w8j4a9.ssl.hwcdn.net/ztvhdusa/tracks-v1a1/playlist.m3u8",
        "http://144.217.70.181:9587/hin2/ZEETVHD/index.m3u8?token=test",
        "http://198.255.94.194:8080/live/zeetv/index.m3u8"
    ]},
    {"id":"sony-sab","name":"Sony SAB","country":"IN","cat":"Entertainment","icon":"😄","streams":[
        "http://216.144.250.174/Sony_Sab_HD/playlist.m3u8",
        "http://bapatv.live:8080/sonysab/index.m3u8"
    ]},
    {"id":"dangal","name":"Dangal TV","country":"IN","cat":"Entertainment","icon":"🔥","streams":[
        "https://live-dangal.akamaized.net/liveabr/playlist.m3u8"
    ]},
    {"id":"star-bharat","name":"Star Bharat","country":"IN","cat":"Entertainment","icon":"⭐","streams":[
        "http://bapatv.live:8080/starbharat/index.m3u8"
    ]},
    {"id":"star-utsav","name":"Star Utsav","country":"IN","cat":"Entertainment","icon":"⭐","streams":[
        "http://bapatv.live:8080/starutsav/index.m3u8"
    ]},
    {"id":"and-tv","name":"&TV","country":"IN","cat":"Entertainment","icon":"🎬","streams":[
        "http://bapatv.live:8080/andtv/index.m3u8"
    ]},
    {"id":"sab-tv-hd","name":"SAB TV HD","country":"IN","cat":"Entertainment","icon":"😄","streams":[
        "http://bapatv.live:8080/sabtvhd/index.m3u8"
    ]},
    {"id":"dd-national","name":"DD National","country":"IN","cat":"Entertainment","icon":"🇮🇳","streams":[
        "https://d3o3cim6uzorb4.cloudfront.net/out/v1/0f43e0e4e2ec42cdbe2d6a13e45c1ef9/index.m3u8"
    ]},

    # ══ INDIA — NEWS ══
    {"id":"aaj-tak","name":"Aaj Tak","country":"IN","cat":"News","icon":"📺","streams":[
        "https://feeds.intoday.in/aajtak/api/master.m3u8",
        "http://5.254.16.186/AajTak/index.m3u8"
    ]},
    {"id":"ndtv-24x7","name":"NDTV 24x7","country":"IN","cat":"News","icon":"📺","streams":[
        "https://ndtv24x7elemarchana.akamaized.net/hls/live/2003678/ndtv24x7/master.m3u8"
    ]},
    {"id":"india-today","name":"India Today","country":"IN","cat":"News","icon":"📺","streams":[
        "https://feeds.intoday.in/it/api/master.m3u8"
    ]},
    {"id":"republic","name":"Republic TV","country":"IN","cat":"News","icon":"📺","streams":[
        "https://republic.pc.cdn.bitgravity.com/live/d1ea5065d7ee4ac09ec9f7dd74f0f4b9/playlist.m3u8"
    ]},
    {"id":"abp-news","name":"ABP News","country":"IN","cat":"News","icon":"📺","streams":[
        "https://abplive.pc.cdn.bitgravity.com/live/dab92247821e4a3088e1e1f1f1/playlist.m3u8"
    ]},
    {"id":"times-now","name":"Times Now","country":"IN","cat":"News","icon":"📺","streams":[
        "https://timesnow.pc.cdn.bitgravity.com/live/6b8a94dcf3d440/playlist.m3u8"
    ]},
    {"id":"dd-news","name":"DD News","country":"IN","cat":"News","icon":"📺","streams":[
        "https://d3o3cim6uzorb4.cloudfront.net/out/v1/5bccbc9bda404dcc91e1efbd0272d7a0/index.m3u8"
    ]},

    # ══ GLOBAL ══
    {"id":"dw-english","name":"DW English","country":"DE","cat":"News","icon":"📺","streams":[
        "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8"
    ]},
    {"id":"aljazeera-en","name":"Al Jazeera","country":"QA","cat":"News","icon":"📺","streams":[
        "https://live-hls-web-aje.getaj.net/AJE/index.m3u8"
    ]}
]

@app.route("/api/livetv/channels")
def api_ltv_channels():
    c = request.args.get("country","").upper()
    if c:
        items = [x for x in CURATED_CHANNELS if x["country"] == c]
    else:
        items = CURATED_CHANNELS
    return jsonify({"ok": True, "channels": items})

@app.route("/api/livetv/countries")
def api_ltv_countries():
    counts = {}
    for ch in CURATED_CHANNELS:
        counts[ch["country"]] = counts.get(ch["country"], 0) + 1
    names = {"PK":"🇵🇰 Pakistan","IN":"🇮🇳 India","DE":"🇩🇪 Germany","QA":"🇶🇦 Qatar"}
    items = []
    for code in ["PK","IN","DE","QA"]:
        if code in counts:
            items.append({"code":code,"name":names.get(code,code),"count":counts[code]})
    return jsonify({"ok": True, "countries": items})

@app.route("/api/livetv/test-stream")
def api_ltv_test_stream():
    """Test if a stream URL works — HEAD then GET."""
    url = request.args.get("url","").strip()
    if not url: return jsonify({"ok": False, "error": "No URL"}), 400
    try:
        r = requests.head(url, timeout=6, allow_redirects=True)
        if r.status_code in (200, 206):
            return jsonify({"ok": True, "status": r.status_code, "method": "HEAD"})
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=6, stream=True)
        r.close()
        if r.status_code in (200, 206):
            return jsonify({"ok": True, "status": r.status_code, "method": "GET"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:80]})
    return jsonify({"ok": False, "error": "Unreachable"})

# ─── LIVE TV END ───


# ─── VPN HUB START ───

VPN_APPS = [
    {"id":"protonvpn","name":"Proton VPN","icon":"🛡️","pkg":"ch.protonvpn.android",
     "play":"https://play.google.com/store/apps/details?id=ch.protonvpn.android",
     "free":"Unlimited free, no ads, no logs","servers":"5 countries free",
     "best_for":"India + Pakistan servers available"},
    {"id":"windscribe","name":"Windscribe VPN","icon":"💨","pkg":"com.windscribe.vpn",
     "play":"https://play.google.com/store/apps/details?id=com.windscribe.vpn",
     "free":"10 GB/month free","servers":"10+ countries free",
     "best_for":"India + US servers"},
    {"id":"tunnelbear","name":"TunnelBear VPN","icon":"🐻","pkg":"com.tunnelbear.android",
     "play":"https://play.google.com/store/apps/details?id=com.tunnelbear.android",
     "free":"500 MB/month free","servers":"20+ countries",
     "best_for":"Easy one-tap use"},
    {"id":"cloudflare","name":"1.1.1.1 (WARP)","icon":"⚡","pkg":"com.cloudflare.onedotonedotonedotone",
     "play":"https://play.google.com/store/apps/details?id=com.cloudflare.onedotonedotonedotone",
     "free":"Unlimited free, very fast","servers":"Auto nearest",
     "best_for":"Speed + privacy"},
    {"id":"nordvpn","name":"NordVPN","icon":"🎯","pkg":"com.nordvpn.android",
     "play":"https://play.google.com/store/apps/details?id=com.nordvpn.android",
     "free":"7-day trial","servers":"60 countries",
     "best_for":"Best streaming unlock"},
    {"id":"surfshark","name":"Surfshark","icon":"🦈","pkg":"com.surfshark.vpnclient.android",
     "play":"https://play.google.com/store/apps/details?id=com.surfshark.vpnclient.android",
     "free":"7-day trial","servers":"100 countries",
     "best_for":"Unlimited devices"},
    {"id":"turbovpn","name":"Turbo VPN","icon":"🚀","pkg":"free.vpn.unblock.proxy.turbovpn",
     "play":"https://play.google.com/store/apps/details?id=free.vpn.unblock.proxy.turbovpn",
     "free":"Unlimited free (with ads)","servers":"Many countries",
     "best_for":"Quick free VPN"},
    {"id":"holavpn","name":"Hola VPN","icon":"🌐","pkg":"org.hola",
     "play":"https://play.google.com/store/apps/details?id=org.hola",
     "free":"Unlimited free","servers":"190+ countries",
     "best_for":"India region unlock"},
    {"id":"psiphon","name":"Psiphon","icon":"🌀","pkg":"com.psiphon3",
     "play":"https://play.google.com/store/apps/details?id=com.psiphon3",
     "free":"Unlimited free","servers":"Multiple countries",
     "best_for":"Bypass restrictions"},
    {"id":"lantern","name":"Lantern","icon":"🏮","pkg":"org.getlantern.lantern",
     "play":"https://play.google.com/store/apps/details?id=org.getlantern.lantern",
     "free":"Unlimited free","servers":"Multiple countries",
     "best_for":"Anti-censorship"}
]

INDIAN_APPS = [
    {"id":"jiocinema","name":"JioCinema","icon":"🎬","pkg":"com.jio.media.ondemand",
     "play":"https://play.google.com/store/apps/details?id=com.jio.media.ondemand",
     "note":"Free with Jio SIM — Live TV, IPL, Movies"},
    {"id":"jiotv","name":"JioTV","icon":"📺","pkg":"com.jio.tv",
     "play":"https://play.google.com/store/apps/details?id=com.jio.tv",
     "note":"Free with Jio SIM — 600+ live channels"},
    {"id":"airtel","name":"Airtel Xstream","icon":"🎥","pkg":"com.airtel.tv",
     "play":"https://play.google.com/store/apps/details?id=com.airtel.tv",
     "note":"Free with Airtel SIM — Live TV + Movies"},
    {"id":"hotstar","name":"JioHotstar","icon":"✨","pkg":"in.startv.hotstar",
     "play":"https://play.google.com/store/apps/details?id=in.startv.hotstar",
     "note":"Live sports, TV shows, Movies"},
    {"id":"sonyliv","name":"SonyLIV","icon":"📺","pkg":"com.sonyliv",
     "play":"https://play.google.com/store/apps/details?id=com.sonyliv",
     "note":"Live channels, Original series"},
    {"id":"zee5","name":"ZEE5","icon":"Z","pkg":"com.graymatrix.did",
     "play":"https://play.google.com/store/apps/details?id=com.graymatrix.did",
     "note":"Live TV + ZEE originals"},
    {"id":"mxplayer","name":"MX Player","icon":"🎞️","pkg":"com.mxtech.videoplayer.ad",
     "play":"https://play.google.com/store/apps/details?id=com.mxtech.videoplayer.ad",
     "note":"Free movies + Live channels"},
    {"id":"voot","name":"Voot","icon":"🎪","pkg":"com.tv.voot",
     "play":"https://play.google.com/store/apps/details?id=com.tv.voot",
     "note":"Colors, MTV, Nickelodeon content"},
    {"id":"aha","name":"Aha","icon":"🅰️","pkg":"com.aha.aha",
     "play":"https://play.google.com/store/apps/details?id=com.aha.aha",
     "note":"Tamil & Telugu content"},
    {"id":"sunnxt","name":"Sun NXT","icon":"🌞","pkg":"com.suntv.sunnxt",
     "play":"https://play.google.com/store/apps/details?id=com.suntv.sunnxt",
     "note":"South Indian channels"},
    {"id":"discovery","name":"Discovery+","icon":"🦁","pkg":"com.discovery.discoveryplus.mobile",
     "play":"https://play.google.com/store/apps/details?id=com.discovery.discoveryplus.mobile",
     "note":"Documentary + Live channels"}
]

@app.route("/api/vpn/list")
def api_vpn_list():
    return jsonify({"ok": True, "vpns": VPN_APPS})

@app.route("/api/india-apps/list")
def api_india_apps():
    return jsonify({"ok": True, "apps": INDIAN_APPS})

@app.route("/api/installed-apps")
def api_installed_apps():
    """Check which apps are installed on phone"""
    all_pkgs = [x["pkg"] for x in VPN_APPS] + [x["pkg"] for x in INDIAN_APPS]
    installed = []
    try:
        r = subprocess.run(["pm", "list", "packages"], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            if line.startswith("package:"):
                pkg = line.replace("package:", "").strip()
                if pkg in all_pkgs:
                    installed.append(pkg)
    except Exception as e:
        print(f"pkg check failed: {e}")
    return jsonify({"ok": True, "installed": installed})

@app.route("/api/vpn/connect-guide")
def api_vpn_connect_guide():
    return jsonify({"ok": True, "steps": [
        "Install any VPN from the list",
        "Open VPN app → select India server",
        "Tap Connect",
        "Wait for 'Connected' status",
        "Return to Mano → Live TV → play Indian channels",
        "All geo-blocked channels will work now"
    ]})

# ─── VPN HUB END ───


# ─── ENTERTAINMENT START ───
import html as _html

# ── TV Shows — TVMaze (no key) ──
@app.route("/api/ent/tv/search")
def ent_tv_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify({"ok": False, "error": "No query"})
    try:
        r = requests.get(f"https://api.tvmaze.com/search/shows?q={requests.utils.quote(q)}", timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json()[:24]:
                s = x.get("show", {})
                items.append({
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "premiered": s.get("premiered"),
                    "genres": s.get("genres") or [],
                    "rating": (s.get("rating") or {}).get("average"),
                    "network": ((s.get("network") or {}).get("name") or (s.get("webChannel") or {}).get("name") or "N/A"),
                    "country": ((s.get("network") or {}).get("country") or {}).get("name") or "N/A",
                    "summary": re.sub(r'<[^>]+>', '', s.get("summary") or "")[:200],
                    "image": ((s.get("image") or {}).get("medium")) or ""
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"TVMaze error: {e}")
    return jsonify({"ok": False, "items": []})

# ── Movies — iTunes Search (no key) ──
@app.route("/api/ent/movie/search")
def ent_movie_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify({"ok": False, "error": "No query"})
    try:
        r = requests.get(f"https://itunes.apple.com/search?term={requests.utils.quote(q)}&media=movie&limit=24", timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json().get("results", []):
                items.append({
                    "name": x.get("trackName") or "",
                    "year": (x.get("releaseDate") or "")[:4],
                    "genre": x.get("primaryGenreName") or "",
                    "rating": x.get("contentAdvisoryRating") or "",
                    "director": x.get("artistName") or "",
                    "summary": x.get("longDescription") or x.get("shortDescription") or "",
                    "image": (x.get("artworkUrl100") or "").replace("100x100","400x400"),
                    "preview": x.get("previewUrl") or "",
                    "country": x.get("country") or ""
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"iTunes error: {e}")
    return jsonify({"ok": False, "items": []})

# ── Anime — Jikan (no key) ──
@app.route("/api/ent/anime/search")
def ent_anime_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify({"ok": False, "error": "No query"})
    try:
        r = requests.get(f"https://api.jikan.moe/v4/anime?q={requests.utils.quote(q)}&limit=24", timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json().get("data", []):
                items.append({
                    "name": x.get("title") or "",
                    "name_jp": x.get("title_japanese") or "",
                    "episodes": x.get("episodes"),
                    "status": x.get("status") or "",
                    "score": x.get("score"),
                    "type": x.get("type") or "",
                    "year": (x.get("aired") or {}).get("prop",{}).get("from",{}).get("year"),
                    "genres": [g.get("name") for g in (x.get("genres") or [])],
                    "summary": x.get("synopsis") or "",
                    "image": (x.get("images",{}).get("jpg",{}) or {}).get("image_url") or ""
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Jikan error: {e}")
    return jsonify({"ok": False, "items": []})

# ── Asian Dramas — MyDramaList (scraper, no key) ──
@app.route("/api/ent/drama/search")
def ent_drama_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify({"ok": False, "error": "No query"})
    items = []
    try:
        # Scrape MDL search
        headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"}
        url = f"https://mydramalist.com/search?q={requests.utils.quote(q)}"
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            # Extract JSON-LD or item blocks
            import re as _re
            titles = _re.findall(r'<h6 class="text-primary title"><a href="([^"]+)"[^>]*>([^<]+)</a>', r.text)
            imgs = _re.findall(r'<img[^>]*src="([^"]+)"[^>]*class="img-loading"[^>]*>', r.text)
            metas = _re.findall(r'<span class="text-muted">([^<]+)</span>', r.text)
            # Fallback — parse visible cards
            cards = _re.findall(r'<div class="col-lg-6 col-md-6">(.*?)</div>\s*</div>', r.text, _re.DOTALL)
            for i, (href, title) in enumerate(titles[:20]):
                img = imgs[i] if i < len(imgs) else ""
                meta = metas[i] if i < len(metas) else ""
                items.append({
                    "name": _html.unescape(title.strip()),
                    "url": "https://mydramalist.com" + href,
                    "image": img,
                    "meta": _html.unescape(meta.strip()),
                    "country": "Asian",
                    "source": "MyDramaList"
                })
    except Exception as e:
        print(f"MDL error: {e}")
    return jsonify({"ok": True, "items": items})

# ── TMDB (optional — needs key) ──
@app.route("/api/ent/tmdb/search")
def ent_tmdb_search():
    q = request.args.get("q","").strip()
    api_key = request.args.get("key","").strip()
    media = request.args.get("type","multi")  # multi|movie|tv
    if not q: return jsonify({"ok": False, "error": "No query"})
    if not api_key: return jsonify({"ok": False, "error": "No TMDB API key", "needs_key": True})
    try:
        r = requests.get(f"https://api.themoviedb.org/3/search/{media}?query={requests.utils.quote(q)}&api_key={api_key}", timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json().get("results", [])[:20]:
                items.append({
                    "name": x.get("title") or x.get("name") or "",
                    "type": x.get("media_type") or media,
                    "year": (x.get("release_date") or x.get("first_air_date") or "")[:4],
                    "rating": x.get("vote_average"),
                    "overview": x.get("overview") or "",
                    "image": f"https://image.tmdb.org/t/p/w400{x.get('poster_path')}" if x.get("poster_path") else "",
                    "country": x.get("original_language","").upper()
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"TMDB error: {e}")
    return jsonify({"ok": False, "items": []})

# ── Trending (TVMaze schedule by country) ──
@app.route("/api/ent/trending")
def ent_trending():
    country = request.args.get("country","US").upper()
    try:
        r = requests.get(f"https://api.tvmaze.com/schedule?country={country}", timeout=12)
        if r.status_code == 200:
            items = []
            seen = set()
            for x in r.json()[:60]:
                s = x.get("show", {})
                name = s.get("name")
                if name in seen: continue
                seen.add(name)
                items.append({
                    "name": name,
                    "network": (s.get("network") or {}).get("name") or "",
                    "time": x.get("airtime") or "",
                    "date": x.get("airdate") or "",
                    "image": ((s.get("image") or {}).get("medium")) or "",
                    "summary": re.sub(r'<[^>]+>', '', s.get("summary") or "")[:150]
                })
                if len(items) >= 20: break
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Trending error: {e}")
    return jsonify({"ok": False, "items": []})

# ─── ENTERTAINMENT END ───


# ─── MANO STATS START ───
@app.route("/api/mano/stats")
def mano_stats():
    import time as _t
    def _load(fp):
        if os.path.exists(fp):
            try:
                with open(fp) as f: return json.load(f)
            except: return []
        return []
    notes = _load(os.path.join(BASE_DIR, "notes.json"))
    reminders = _load(os.path.join(BASE_DIR, "reminders.json"))
    journal = _load(os.path.join(BASE_DIR, "journal.json"))
    mood = _load(os.path.join(BASE_DIR, "mood.json"))
    memories = _load(os.path.join(BASE_DIR, "memories.json"))
    today = _t.strftime("%Y-%m-%d")
    today_journal = [j for j in journal if (j.get("date") or "").startswith(today)]
    recent_mood = mood[-1] if mood else {"mood":"neutral","date":""}
    # Journal streak
    dates = set([(j.get("date") or "")[:10] for j in journal])
    streak = 0
    d = _t.time()
    for i in range(60):
        day = _t.strftime("%Y-%m-%d", _t.localtime(d - i*86400))
        if day in dates: streak += 1
        elif i > 0: break
    return jsonify({
        "ok": True,
        "counts": {
            "notes": len(notes),
            "reminders": len(reminders),
            "journal": len(journal),
            "journal_today": len(today_journal),
            "mood": len(mood),
            "memories": len(memories)
        },
        "streak": streak,
        "recent_mood": recent_mood,
        "recent_memories": memories[-5:][::-1],
        "recent_notes": notes[-3:][::-1],
        "today": today
    })
# ─── MANO STATS END ───


# ─── GLOBAL ENT START ───
import html as _html
import time as _time

# ── 1. TRENDING (Simkl — no key, all countries) ──
@app.route("/api/global/trending")
def global_trending():
    """Latest trending movies, TV shows, and anime (no key required)."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    result = {"ok": True, "movies": [], "tv": [], "anime": []}
    try:
        # Simkl trending movies (top 100)
        r = requests.get("https://data.simkl.org/api/v2/trending/movies/100", timeout=12)
        if r.status_code == 200:
            result["movies"] = r.json()[:20]
    except Exception as e:
        print(f"Simkl movies: {e}")
    try:
        r = requests.get("https://data.simkl.org/api/v2/trending/tv/100", timeout=12)
        if r.status_code == 200:
            result["tv"] = r.json()[:20]
    except Exception as e:
        print(f"Simkl TV: {e}")
    try:
        r = requests.get("https://data.simkl.org/api/v2/trending/anime/100", timeout=12)
        if r.status_code == 200:
            result["anime"] = r.json()[:20]
    except Exception as e:
        print(f"Simkl anime: {e}")
    return jsonify(result)

# ── 2. ALL-COUNTRY MOVIES (iTunes — 100+ countries) ──
@app.route("/api/global/movies")
def global_movies():
    """Movies from any country via iTunes Search API."""
    q = request.args.get("q", "latest").strip()
    country = request.args.get("country", "us").lower()
    try:
        url = f"https://itunes.apple.com/search?term={requests.utils.quote(q)}&media=movie&limit=25&country={country}"
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json().get("results", []):
                items.append({
                    "name": x.get("trackName") or "",
                    "year": (x.get("releaseDate") or "")[:4],
                    "genre": x.get("primaryGenreName") or "",
                    "country": x.get("country") or country.upper(),
                    "director": x.get("artistName") or "",
                    "summary": x.get("longDescription") or x.get("shortDescription") or "",
                    "image": (x.get("artworkUrl100") or "").replace("100x100", "400x400"),
                    "preview": x.get("previewUrl") or "",
                    "source": "iTunes"
                })
            return jsonify({"ok": True, "items": items, "country": country})
    except Exception as e:
        print(f"iTunes: {e}")
    return jsonify({"ok": False, "items": []})

# ── 3. ALL-COUNTRY TV SHOWS (TVMaze — 80,000+ shows, any country) ──
@app.route("/api/global/tv")
def global_tv():
    """TV shows from any country via TVMaze (no key)."""
    q = request.args.get("q", "latest").strip()
    try:
        url = f"https://api.tvmaze.com/search/shows?q={requests.utils.quote(q)}"
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json()[:25]:
                s = x.get("show", {})
                items.append({
                    "name": s.get("name") or "",
                    "status": s.get("status") or "",
                    "premiered": s.get("premiered") or "",
                    "genres": s.get("genres") or [],
                    "rating": (s.get("rating") or {}).get("average"),
                    "network": ((s.get("network") or {}).get("name") or (s.get("webChannel") or {}).get("name") or "N/A"),
                    "country": ((s.get("network") or {}).get("country") or {}).get("name") or "N/A",
                    "summary": re.sub(r'<[^>]+>', '', s.get("summary") or "")[:200],
                    "image": ((s.get("image") or {}).get("medium")) or "",
                    "source": "TVMaze"
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"TVMaze: {e}")
    return jsonify({"ok": False, "items": []})

# ── 4. ASIAN DRAMAS (Dramacool API — Korean, Japanese, Chinese, Thai, Pakistani) ──
@app.route("/api/global/dramas")
def global_dramas():
    """Asian dramas — Korean, Japanese, Chinese, Thai, Taiwanese, Filipino."""
    q = request.args.get("q", "latest").strip()
    country = request.args.get("country", "").lower()
    try:
        # Dramacool REST API (free, no key)
        url = f"https://api.xyra.stream/v1/dramacool/search?q={requests.utils.quote(q)}"
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            data = r.json()
            items = []
            for x in (data.get("results") or [])[:25]:
                items.append({
                    "name": x.get("title") or x.get("name") or "",
                    "poster": x.get("image") or x.get("poster") or "",
                    "country": x.get("country") or country.upper() or "Asian",
                    "year": x.get("year") or "",
                    "episodes": x.get("episodes") or "",
                    "status": x.get("status") or "",
                    "url": x.get("url") or "",
                    "source": "Dramacool"
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Dramacool: {e}")
    # Fallback: search via DuckDuckGo
    try:
        query = f"{q} drama watch online"
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            snippets = re.findall(r'class="result__snippet">(.*?)</a>', r.text, re.DOTALL)
            items = []
            for i, s in enumerate(snippets[:15]):
                items.append({
                    "name": _html.unescape(re.sub(r'<[^>]+>', '', s).strip())[:120],
                    "country": country.upper() or "Asian",
                    "source": "Web Search"
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Drama fallback: {e}")
    return jsonify({"ok": False, "items": []})

# ── 5. ANIME (Jikan / MyAnimeList — all countries) ──
@app.route("/api/global/anime")
def global_anime():
    """Anime from Japan — trending, top, seasonal."""
    q = request.args.get("q", "").strip()
    try:
        if q:
            url = f"https://api.jikan.moe/v4/anime?q={requests.utils.quote(q)}&limit=25"
        else:
            url = "https://api.jikan.moe/v4/top/anime?limit=25"
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            items = []
            for x in r.json().get("data", []):
                items.append({
                    "name": x.get("title") or "",
                    "name_jp": x.get("title_japanese") or "",
                    "episodes": x.get("episodes"),
                    "status": x.get("status") or "",
                    "score": x.get("score"),
                    "type": x.get("type") or "",
                    "year": (x.get("aired") or {}).get("prop", {}).get("from", {}).get("year"),
                    "genres": [g.get("name") for g in (x.get("genres") or [])],
                    "summary": x.get("synopsis") or "",
                    "image": (x.get("images", {}).get("jpg", {}) or {}).get("image_url") or "",
                    "source": "Jikan/MAL"
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Jikan: {e}")
    return jsonify({"ok": False, "items": []})

# ── 6. AIRING TODAY (TVMaze schedule — all countries) ──
@app.route("/api/global/airing")
def global_airing():
    """Shows airing today in any country."""
    country = request.args.get("country", "US").upper()
    try:
        r = requests.get(f"https://api.tvmaze.com/schedule?country={country}", timeout=12)
        if r.status_code == 200:
            items = []
            seen = set()
            for x in r.json():
                s = x.get("show", {})
                name = s.get("name")
                if name in seen: continue
                seen.add(name)
                items.append({
                    "name": name,
                    "network": (s.get("network") or {}).get("name") or "",
                    "time": x.get("airtime") or "",
                    "date": x.get("airdate") or "",
                    "image": ((s.get("image") or {}).get("medium")) or "",
                    "summary": re.sub(r'<[^>]+>', '', s.get("summary") or "")[:150],
                    "country": country,
                    "source": "TVMaze Schedule"
                })
                if len(items) >= 25: break
            return jsonify({"ok": True, "items": items, "country": country})
    except Exception as e:
        print(f"Schedule: {e}")
    return jsonify({"ok": False, "items": []})

# ── 7. COUNTRY LIST ──
@app.route("/api/global/countries")
def global_countries():
    """All supported countries for content."""
    return jsonify({"ok": True, "countries": [
        {"code":"us","name":"🇺🇸 USA"},
        {"code":"gb","name":"🇬🇧 UK"},
        {"code":"in","name":"🇮🇳 India"},
        {"code":"pk","name":"🇵🇰 Pakistan"},
        {"code":"kr","name":"🇰🇷 Korea"},
        {"code":"jp","name":"🇯🇵 Japan"},
        {"code":"cn","name":"🇨🇳 China"},
        {"code":"th","name":"🇹🇭 Thailand"},
        {"code":"tr","name":"🇹🇷 Turkey"},
        {"code":"ph","name":"🇵🇭 Philippines"},
        {"code":"id","name":"🇮🇩 Indonesia"},
        {"code":"de","name":"🇩🇪 Germany"},
        {"code":"fr","name":"🇫🇷 France"},
        {"code":"es","name":"🇪🇸 Spain"},
        {"code":"it","name":"🇮🇹 Italy"},
        {"code":"br","name":"🇧🇷 Brazil"},
        {"code":"mx","name":"🇲🇽 Mexico"},
        {"code":"ru","name":"🇷🇺 Russia"},
        {"code":"nl","name":"🇳🇱 Netherlands"},
        {"code":"ng","name":"🇳🇬 Nigeria"}
    ]})

# ─── GLOBAL ENT END ───


# ─── MX PLAYER START ───

@app.route("/api/mx/play", methods=["POST","OPTIONS"])
def mx_play():
    """Launch a video URL in MX Player (or fallback to VLC / default player)."""
    if request.method == "OPTIONS": return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    title = (data.get("title") or "Video").strip()
    if not url: return jsonify({"ok": False, "error": "No URL"}), 400

    # MX Player packages to try (in order)
    packages = [
        "com.mxtech.videoplayer.ad",     # MX Player Free
        "com.mxtech.videoplayer.pro",    # MX Player Pro
        "org.videolan.vlc",              # VLC fallback
        "com.google.android.exoplayer2.demo",
    ]

    # Check which packages are installed
    installed = []
    try:
        r = subprocess.run(["pm","list","packages"], capture_output=True, text=True, timeout=10)
        all_pkgs = [l.replace("package:","").strip() for l in r.stdout.splitlines() if l.startswith("package:")]
        for p in packages:
            if p in all_pkgs:
                installed.append(p)
    except Exception as e:
        print(f"pkg check failed: {e}")

    if not installed:
        return jsonify({"ok": False, "error": "MX Player / VLC not installed",
                        "install_mx": "https://play.google.com/store/apps/details?id=com.mxtech.videoplayer.ad"})

    # Try each package
    for pkg in installed:
        try:
            # Method 1: direct VIEW intent with package
            r = subprocess.run([
                "am","start",
                "-a","android.intent.action.VIEW",
                "-d", url,
                "-t","video/*",
                "-n", pkg + "/" + ("com.mxtech.videoplayer.ad.ActivityWelcomeMX" if "mxtech" in pkg else "org.videolan.vlc.gui.video.VideoPlayerActivity"),
                "--grant-read-uri-permission"
            ], capture_output=True, text=True, timeout=8)

            if r.returncode == 0:
                return jsonify({"ok": True, "player": pkg, "title": title, "url": url})

            # Method 2: generic intent
            r2 = subprocess.run([
                "am","start",
                "-a","android.intent.action.VIEW",
                "-d", url,
                "-t","video/*",
                "-p", pkg,
            ], capture_output=True, text=True, timeout=8)
            if r2.returncode == 0:
                return jsonify({"ok": True, "player": pkg, "title": title, "url": url})
        except Exception as e:
            print(f"mx try {pkg}: {e}")
            continue

    return jsonify({"ok": False, "error": "Failed to launch MX Player"})

@app.route("/api/mx/search-movie")
def mx_search_movie():
    """Search movies — returns metadata + YouTube trailer URL for MX Player."""
    q = request.args.get("q","").strip()
    if not q: return jsonify({"ok": False, "error": "No query"}), 400
    items = []
    # iTunes for movie metadata
    try:
        r = requests.get(f"https://itunes.apple.com/search?term={requests.utils.quote(q)}&media=movie&limit=15", timeout=12)
        if r.status_code == 200:
            for x in r.json().get("results", []):
                items.append({
                    "name": x.get("trackName") or "",
                    "year": (x.get("releaseDate") or "")[:4],
                    "genre": x.get("primaryGenreName") or "",
                    "summary": x.get("longDescription") or x.get("shortDescription") or "",
                    "image": (x.get("artworkUrl100") or "").replace("100x100","400x400"),
                    "trailer": x.get("previewUrl") or "",
                    "youtube_search": "https://www.youtube.com/results?search_query=" + requests.utils.quote((x.get("trackName") or "") + " full movie"),
                    "type": "movie"
                })
    except Exception as e:
        print(f"iTunes: {e}")
    # TVMaze for TV shows
    try:
        r = requests.get(f"https://api.tvmaze.com/search/shows?q={requests.utils.quote(q)}", timeout=12)
        if r.status_code == 200:
            for x in r.json()[:10]:
                s = x.get("show", {})
                items.append({
                    "name": s.get("name") or "",
                    "year": (s.get("premiered") or "")[:4],
                    "genre": ", ".join(s.get("genres") or []),
                    "summary": re.sub(r'<[^>]+>', '', s.get("summary") or "")[:200],
                    "image": ((s.get("image") or {}).get("medium")) or "",
                    "trailer": "",
                    "youtube_search": "https://www.youtube.com/results?search_query=" + requests.utils.quote((s.get("name") or "") + " trailer"),
                    "type": "tv"
                })
    except Exception as e:
        print(f"TVMaze: {e}")
    return jsonify({"ok": True, "items": items})

@app.route("/api/mx/archive-search")
def mx_archive_search():
    """Search Internet Archive for full public-domain movies that play in MX Player."""
    q = request.args.get("q","").strip() or "classic movies"
    try:
        url = f"https://archive.org/advancedsearch.php?q={requests.utils.quote(q + ' AND mediatype:movies')}&fl[]=identifier&fl[]=title&fl[]=year&fl[]=description&fl[]=downloads&rows=20&output=json"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            items = []
            for doc in r.json().get("response", {}).get("docs", []):
                ident = doc.get("identifier")
                if not ident: continue
                # Try mp4 or m3u8 direct URL
                stream_url = f"https://archive.org/download/{ident}/format=h.264"
                # Better: check metadata for actual file
                try:
                    mr = requests.get(f"https://archive.org/metadata/{ident}", timeout=8)
                    if mr.status_code == 200:
                        files = mr.json().get("files", [])
                        best = None
                        for f in files:
                            n = f.get("name", "")
                            if n.endswith(".mp4") or n.endswith(".m4v") or n.endswith(".mkv"):
                                best = f"https://archive.org/download/{ident}/{n}"
                                break
                            if n.endswith(".m3u8") and not best:
                                best = f"https://archive.org/download/{ident}/{n}"
                        if best:
                            stream_url = best
                except: pass
                items.append({
                    "name": doc.get("title") or "",
                    "year": doc.get("year") or "",
                    "summary": (doc.get("description") or "")[:200] if isinstance(doc.get("description"), str) else "",
                    "stream": stream_url,
                    "source": "Internet Archive",
                    "type": "public-domain movie"
                })
            return jsonify({"ok": True, "items": items})
    except Exception as e:
        print(f"Archive: {e}")
    return jsonify({"ok": False, "items": []})

# ─── MX PLAYER END ───


# ─── PREMIUM TOOLS START ───
import random as _rnd

# Habit tracker
HABITS_FILE = os.path.join(BASE_DIR, "habits.json")
EXPENSES_FILE = os.path.join(BASE_DIR, "expenses.json")
BIRTHDAYS_FILE = os.path.join(BASE_DIR, "birthdays.json")
VAULT_FILE = os.path.join(BASE_DIR, "vault.json")

def _load(fp):
    if os.path.exists(fp):
        try:
            with open(fp) as f: return json.load(f)
        except: return []
    return []
def _save(fp, d):
    with open(fp,'w') as f: json.dump(d, f, indent=2)

# ── Habits ──
@app.route("/api/habits", methods=["GET","POST","DELETE"])
def api_habits():
    if request.method == "GET": return jsonify(_load(HABITS_FILE))
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(HABITS_FILE)
        action = d.get("action","add")
        if action == "add":
            items.append({"id": int(time.time()), "name": d.get("name",""), "icon": d.get("icon","✅"),
                          "history": []})
        elif action == "check":
            hid = d.get("id"); today = time.strftime("%Y-%m-%d")
            for h in items:
                if h["id"] == hid:
                    hist = h.get("history", [])
                    if today in hist: hist.remove(today)
                    else: hist.append(today)
                    h["history"] = hist
                    break
        _save(HABITS_FILE, items)
        return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(HABITS_FILE, [i for i in _load(HABITS_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

# ── Expenses ──
@app.route("/api/expenses", methods=["GET","POST","DELETE"])
def api_expenses():
    if request.method == "GET": return jsonify(_load(EXPENSES_FILE))
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(EXPENSES_FILE)
        items.append({"id": int(time.time()), "amount": float(d.get("amount",0)),
                      "category": d.get("category","other"), "note": d.get("note",""),
                      "date": time.strftime("%Y-%m-%d %H:%M")})
        _save(EXPENSES_FILE, items)
        return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(EXPENSES_FILE, [i for i in _load(EXPENSES_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

# ── Birthdays ──
@app.route("/api/birthdays", methods=["GET","POST","DELETE"])
def api_birthdays():
    if request.method == "GET": return jsonify(_load(BIRTHDAYS_FILE))
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(BIRTHDAYS_FILE)
        items.append({"id": int(time.time()), "name": d.get("name",""),
                      "date": d.get("date",""), "relation": d.get("relation","")})
        _save(BIRTHDAYS_FILE, items)
        return jsonify({"ok": True, "items": items})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(BIRTHDAYS_FILE, [i for i in _load(BIRTHDAYS_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

# ── Password Vault (basic base64 — for demo only) ──
import base64 as _b64
@app.route("/api/vault", methods=["GET","POST","DELETE"])
def api_vault():
    if request.method == "GET":
        items = _load(VAULT_FILE)
        # Don't send actual passwords
        safe = [{"id": i["id"], "label": i["label"], "username": i["username"]} for i in items]
        return jsonify(safe)
    if request.method == "POST":
        d = request.get_json() or {}
        items = _load(VAULT_FILE)
        items.append({"id": int(time.time()), "label": d.get("label",""),
                      "username": d.get("username",""),
                      "password": _b64.b64encode((d.get("password","")).encode()).decode()})
        _save(VAULT_FILE, items)
        return jsonify({"ok": True})
    if request.method == "DELETE":
        d = request.get_json() or {}
        _save(VAULT_FILE, [i for i in _load(VAULT_FILE) if i.get("id") != d.get("id")])
        return jsonify({"ok": True})

@app.route("/api/vault/reveal/<int:vid>")
def api_vault_reveal(vid):
    items = _load(VAULT_FILE)
    for i in items:
        if i["id"] == vid:
            try: pw = _b64.b64decode(i["password"]).decode()
            except: pw = ""
            return jsonify({"ok": True, "password": pw})
    return jsonify({"ok": False}), 404

# ── Weekly Report ──
@app.route("/api/weekly-report")
def api_weekly_report():
    def _count(fp): return len(_load(fp))
    notes = _count(os.path.join(BASE_DIR,"notes.json"))
    rems = _count(os.path.join(BASE_DIR,"reminders.json"))
    jr = _count(os.path.join(BASE_DIR,"journal.json"))
    mem = _count(os.path.join(BASE_DIR,"memories.json"))
    hab = _load(HABITS_FILE)
    today = time.strftime("%Y-%m-%d")
    week_start = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7*86400))
    habit_checks = 0
    for h in hab:
        for d in h.get("history", []):
            if d >= week_start: habit_checks += 1
    exp = _load(EXPENSES_FILE)
    week_exp = sum([e.get("amount",0) for e in exp if (e.get("date","")[:10] >= week_start)])
    return jsonify({
        "ok": True,
        "notes": notes, "reminders": rems, "journal": jr,
        "memories": mem, "habit_checks": habit_checks,
        "week_expense": round(week_exp, 2),
        "period": week_start + " → " + today
    })

# ── Quote of the Day ──
@app.route("/api/quote")
def api_quote():
    quotes = [
        {"text":"The secret of getting ahead is getting started.", "author":"Mark Twain"},
        {"text":"It always seems impossible until it's done.", "author":"Nelson Mandela"},
        {"text":"Don't watch the clock; do what it does. Keep going.", "author":"Sam Levenson"},
        {"text":"The best way to predict the future is to invent it.", "author":"Alan Kay"},
        {"text":"Success is not final, failure is not fatal.", "author":"Winston Churchill"},
        {"text":"Believe you can and you're halfway there.", "author":"Theodore Roosevelt"},
        {"text":"The only way to do great work is to love what you do.", "author":"Steve Jobs"},
        {"text":"Hardships often prepare ordinary people for an extraordinary destiny.", "author":"C.S. Lewis"},
        {"text":"Everything you've ever wanted is on the other side of fear.", "author":"George Addair"},
        {"text":"You don't have to be great to start, but you have to start to be great.", "author":"Zig Ziglar"},
        {"text":"Small daily improvements are the key to staggering long-term results.", "author":"Robin Sharma"},
        {"text":"The future belongs to those who believe in the beauty of their dreams.", "author":"Eleanor Roosevelt"}
    ]
    # Deterministic by day
    seed = int(time.time() / 86400)
    _rnd.seed(seed)
    q = _rnd.choice(quotes)
    return jsonify({"ok": True, "quote": q})

# ── Unit Converter ──
@app.route("/api/convert")
def api_convert():
    val = float(request.args.get("v",0))
    frm = request.args.get("from","km").lower()
    to = request.args.get("to","mi").lower()
    # Length
    lengths = {"km":1000,"m":1,"cm":0.01,"mm":0.001,"mi":1609.344,"yd":0.9144,"ft":0.3048,"in":0.0254}
    # Weight
    weights = {"kg":1,"g":0.001,"mg":0.000001,"lb":0.453592,"oz":0.0283495,"ton":1000}
    # Temp special case
    if frm in ("c","f","k") and to in ("c","f","k"):
        if frm == "c": base = val
        elif frm == "f": base = (val-32)*5/9
        else: base = val - 273.15
        if to == "c": r = base
        elif to == "f": r = base*9/5+32
        else: r = base + 273.15
        return jsonify({"ok": True, "result": round(r, 4), "unit": to})
    if frm in lengths and to in lengths:
        r = val * lengths[frm] / lengths[to]
        return jsonify({"ok": True, "result": round(r, 6), "unit": to})
    if frm in weights and to in weights:
        r = val * weights[frm] / weights[to]
        return jsonify({"ok": True, "result": round(r, 6), "unit": to})
    return jsonify({"ok": False, "error": "Unsupported conversion"})

# ── Translator ──
@app.route("/api/translate")
def api_translate():
    text = request.args.get("text","").strip()
    to = request.args.get("to","ur")
    if not text: return jsonify({"ok": False, "error": "No text"})
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={to}&dt=t&q={requests.utils.quote(text)}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            translated = "".join([x[0] for x in data[0] if x[0]])
            return jsonify({"ok": True, "translated": translated, "to": to})
    except Exception as e:
        print(f"translate: {e}")
    return jsonify({"ok": False})

# ── Focus Timer (Pomodoro stats) ──
FOCUS_FILE = os.path.join(BASE_DIR, "focus.json")
@app.route("/api/focus", methods=["GET","POST"])
def api_focus():
    if request.method == "GET":
        items = _load(FOCUS_FILE)
        today = time.strftime("%Y-%m-%d")
        today_sessions = [x for x in items if (x.get("date","")[:10] == today)]
        week_start = time.strftime("%Y-%m-%d", time.localtime(time.time()-7*86400))
        week_sessions = [x for x in items if (x.get("date","")[:10] >= week_start)]
        return jsonify({"ok": True, "today": len(today_sessions),
                        "week": len(week_sessions), "total": len(items),
                        "today_minutes": sum(x.get("minutes",0) for x in today_sessions),
                        "week_minutes": sum(x.get("minutes",0) for x in week_sessions)})
    d = request.get_json() or {}
    items = _load(FOCUS_FILE)
    items.append({"id": int(time.time()), "minutes": int(d.get("minutes",25)),
                  "label": d.get("label","Focus"), "date": time.strftime("%Y-%m-%d %H:%M")})
    _save(FOCUS_FILE, items)
    return jsonify({"ok": True})

# ── Health Dashboard ──
@app.route("/api/health-dashboard")
def api_health_dashboard():
    out = {"ok": True}
    try:
        r = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            b = json.loads(r.stdout)
            out["battery"] = {"level": b.get("percentage"), "temp": b.get("temperature"),
                              "health": b.get("health"), "plugged": b.get("plugged")}
    except: pass
    try:
        r = subprocess.run(["df","-h","/data"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "/data" in line:
                parts = line.split()
                out["storage"] = {"total": parts[1], "used": parts[2],
                                  "free": parts[3], "percent": parts[4]}
                break
    except: pass
    return jsonify(out)

# ─── PREMIUM TOOLS END ───


# ─── MANO FIX ROUTES ───
@app.route("/open-app", methods=["POST", "OPTIONS"])
def open_app():
    if request.method == "OPTIONS": return jsonify({"ok": True})
    d = request.get_json(silent=True) or {}
    app_id = (d.get("app") or "").strip()
    if not app_id:
        return jsonify({"ok": False, "error": "no app"})
    try:
        r = subprocess.run(
            ["monkey", "-p", app_id, "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True, text=True, timeout=8)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "No activities found" not in out:
            return jsonify({"ok": True, "app": app_id, "method": "monkey"})
    except Exception:
        pass
    for activity in [".MainActivity", ".activity.MainActivity"]:
        try:
            r2 = subprocess.run(
                ["am", "start", "-n", app_id + "/" + activity.lstrip("/")],
                capture_output=True, text=True, timeout=6)
            out2 = (r2.stdout or "") + (r2.stderr or "")
            if r2.returncode == 0 and "Error" not in out2:
                return jsonify({"ok": True, "app": app_id, "method": "am"})
        except Exception:
            continue
    try:
        r3 = subprocess.run(
            ["am", "start", "-a", "android.intent.action.MAIN",
             "-c", "android.intent.category.LAUNCHER", "-p", app_id],
            capture_output=True, text=True, timeout=6)
        if r3.returncode == 0:
            return jsonify({"ok": True, "app": app_id, "method": "intent"})
    except Exception:
        pass
    return jsonify({"ok": False, "error": "not installed or blocked", "app": app_id})


@app.route("/api/markets")
def markets_api():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,solana,binancecoin,ripple,dogecoin"
            "&vs_currencies=usd&include_24hr_change=true",
            timeout=10)
        if r.status_code == 200:
            return jsonify({"ok": True, "coins": r.json()})
        return jsonify({"ok": False, "error": "coingecko " + str(r.status_code)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]})




# ─── MANO WEATHER (free, no key) ───
@app.route("/api/weather")
def weather_api():
    city = request.args.get("city", "Karachi").strip() or "Karachi"
    try:
        r = requests.get(
            "https://wttr.in/" + requests.utils.quote(city) + "?format=j1",
            timeout=12, headers={"User-Agent": "curl/8.0"})
        if r.status_code == 200:
            d = r.json()
            cur = d.get("current_condition", [{}])[0]
            return jsonify({
                "ok": True,
                "city": city,
                "temp_c": cur.get("temp_C", "?"),
                "temp_f": cur.get("temp_F", "?"),
                "desc": (cur.get("weatherDesc") or [{}])[0].get("value", "Clear"),
                "humidity": cur.get("humidity", "?"),
                "wind_kmph": cur.get("windspeedKmph", "?"),
                "feels_like": cur.get("FeelsLikeC", "?"),
                "observation_time": cur.get("observation_time", "")
            })
    except Exception as e:
        print(f"weather: {e}")
    return jsonify({"ok": False, "city": city, "temp_c": "?", "desc": "Unavailable"})




# ─── MANO PREMIUM TOOLS ───
import datetime as _dt

PRAYER_CACHE = {}

@app.route("/api/prayer-times")
def prayer_times():
    """Prayer times via AlAdhan (free, no key). Cached per day per city."""
    city = request.args.get("city", "").strip()
    country = request.args.get("country", "Pakistan").strip()
    lat = request.args.get("lat", "").strip()
    lng = request.args.get("lng", "").strip()
    method = request.args.get("method", "1")  # 1 = Karachi (Univ. of Islamic Sciences)

    today = _dt.date.today().isoformat()
    cache_key = "{}|{}|{}|{}|{}".format(city, country, lat, lng, today)
    if cache_key in PRAYER_CACHE:
        return jsonify(PRAYER_CACHE[cache_key])

    try:
        params = {"method": method}
        if lat and lng:
            params["latitude"] = lat
            params["longitude"] = lng
        else:
            params["city"] = city or "Karachi"
            params["country"] = country

        r = requests.get("https://api.aladhan.com/v1/timingsByCity" if not (lat and lng)
                         else "https://api.aladhan.com/v1/timings",
                         params=params, timeout=12)
        if r.status_code == 200:
            data = r.json().get("data", {})
            timings = data.get("timings", {})
            date_info = data.get("date", {})
            hijri = date_info.get("hijri", {})
            result = {
                "ok": True,
                "city": city or data.get("meta", {}).get("timezone", "Local"),
                "date": date_info.get("readable", ""),
                "hijri": "{} {} {}".format(hijri.get("day", ""), hijri.get("month", {}).get("en", ""), hijri.get("year", "")),
                "hijri_ar": hijri.get("month", {}).get("ar", ""),
                "timings": {
                    "Fajr":    timings.get("Fajr", ""),
                    "Sunrise": timings.get("Sunrise", ""),
                    "Dhuhr":   timings.get("Dhuhr", ""),
                    "Asr":     timings.get("Asr", ""),
                    "Maghrib": timings.get("Maghrib", ""),
                    "Isha":    timings.get("Isha", "")
                }
            }
            PRAYER_CACHE[cache_key] = result
            return jsonify(result)
    except Exception as e:
        print("prayer: " + str(e))
    return jsonify({"ok": False, "error": "unavailable"})


@app.route("/api/word-of-day")
def word_of_day():
    """Random English word with definition via dictionaryapi.dev."""
    import random as _random
    words = [
        "serendipity","ephemeral","resilient","eloquent","luminescence",
        "solitude","wanderlust","petrichor","sonder","ethereal",
        "halcyon","zephyr","mellifluous","obfuscate","ebullient",
        "nebulous","quixotic","aplomb","candid","veracity",
        "ameliorate","sagacious","limerence","sonorous","pellucid",
        "urbane","gossamer","ineffable","raconteur","vociferous"
    ]
    seed = int(_dt.date.today().strftime("%Y%m%d"))
    _random.seed(seed)
    w = _random.choice(words)
    try:
        r = requests.get("https://api.dictionaryapi.dev/api/v2/entries/en/" + w, timeout=10)
        if r.status_code == 200:
            data = r.json()[0]
            meaning = ""
            example = ""
            if data.get("meanings"):
                m0 = data["meanings"][0]
                if m0.get("definitions"):
                    meaning = m0["definitions"][0].get("definition", "")
                    example = m0["definitions"][0].get("example", "")
            return jsonify({
                "ok": True, "word": w,
                "phonetic": data.get("phonetic", ""),
                "meaning": meaning,
                "example": example,
                "part_of_speech": (data.get("meanings") or [{}])[0].get("partOfSpeech", "")
            })
    except Exception as e:
        print("wod: " + str(e))
    return jsonify({"ok": True, "word": w, "meaning": "Word of the day", "phonetic": "", "example": ""})


@app.route("/api/affirmation")
def affirmation():
    """Day-deterministic positive affirmation."""
    import random as _random
    affs = [
        "You are exactly where you need to be right now.",
        "Your pace is your pace — no one else's.",
        "Small steps every day beat big leaps once in a while.",
        "You are allowed to rest without earning it first.",
        "Your feelings are valid, even the messy ones.",
        "You've survived every hard day so far. Today is no different.",
        "Progress isn't always visible — but it's happening.",
        "You don't have to be perfect to be worthy of love.",
        "The fact that you keep trying says everything about you.",
        "You are more than your productivity.",
        "Be as kind to yourself as you are to your friends.",
        "Even the sun sets — rest is part of the process.",
        "You are allowed to change your mind.",
        "The right people will never make you shrink.",
        "Your sensitivity is a strength, not a weakness.",
        "You don't need to have it all figured out today.",
        "Showing up is 90% of the work.",
        "Your worth isn't tied to your achievements.",
        "It's okay to outgrow things that no longer fit.",
        "You are doing better than you think.",
        "Every day you're becoming more yourself.",
        "You deserve the same grace you give others.",
        "Slowness is not failure.",
        "The best is yet to come, inshaAllah.",
        "You are enough, exactly as you are.",
        "Your story matters.",
        "You can begin again at any age, any time.",
        "The softest hearts are often the strongest.",
        "You are not behind — you're on your own timeline.",
        "Today is a gift. Be gentle with it."
    ]
    seed = int(_dt.date.today().strftime("%Y%m%d"))
    _random.seed(seed + 7)
    return jsonify({"ok": True, "text": _random.choice(affs)})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True, use_reloader=False)
