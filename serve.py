# Serves public/ to the Cloudflare tunnel (plain HTTP inside Docker; Cloudflare does HTTPS).
# Runs on the python:3.12-slim image the Blade already has, so nothing new lands on its eMMC.
# Counts page views and button taps per day in data/counts.json: numbers only, no IPs, no visitor cookies.
# /admin shows them after logging in with ADMIN_PASSWORD from .env, and edits the page's name and bio
# (saved in data/profile.json, so ./deploy.sh never overwrites them).
import hashlib
import hmac
import html
import io
import json
import os
import re
import sys
import threading
import time
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SRV = os.environ.get("SRV", "/srv")
DATA = os.environ.get("DATA", "/data")
COUNTS = os.path.join(DATA, "counts.json")
PROFILE = os.path.join(DATA, "profile.json")
PORT = int(os.environ.get("PORT", "8000"))
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")  # empty: admin page is off
BOTS = re.compile(r"bot|crawl|spider|preview|facebookexternalhit|whatsapp|curl|wget|python", re.I)
MONTH = 30 * 86400
H1 = re.compile(r"<h1>(.*?)</h1>", re.S)
BIO = re.compile(r'<p class="bio">(.*?)</p>', re.S)

# The page and its buttons, read once (deploy.sh restarts this server, so edits to index.html show up here)
with open(os.path.join(SRV, "index.html"), encoding="utf-8") as f:
    INDEX = f.read()
LINKS = [(url, label.strip()) for url, label in re.findall(r'<a href="(https?://[^"]+)"[^>]*>([^<]+)', INDEX)]


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # a corrupt file stops the server instead of being overwritten
    except FileNotFoundError:
        return default


def save(path, obj):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)  # never leaves a half-written file


counts = load(COUNTS, {})
profile = {"name": html.unescape(H1.search(INDEX).group(1)),
           "bio": html.unescape(BIO.search(INDEX).group(1).replace("<br>", "\n")), **load(PROFILE, {})}
lock = threading.Lock()
fails = {}  # ip -> recent failed login times, in memory only


def bump(*keys):
    day = date.today().isoformat()
    with lock:
        d = counts
        for k in keys:
            d = d.setdefault(k, {})
        d[day] = d.get(day, 0) + 1
        try:
            save(COUNTS, counts)
        except OSError as e:
            print("counts not saved:", e, file=sys.stderr)  # a full or read-only disk must not take the page down


def totals(days):
    today = date.today()
    since = [(today - timedelta(days=n - 1)).isoformat() for n in (1, 7, 30)]
    return [sum(v for d, v in days.items() if d >= s) for s in since] + [sum(days.values())]


def sign(exp):
    return hmac.new(PASSWORD.encode(), f"admin {exp}".encode(), hashlib.sha256).hexdigest()


def index_page():
    with lock:
        name, bio = html.escape(profile["name"]), "<br>".join(html.escape(line) for line in profile["bio"].split("\n"))
    page = H1.sub(lambda m: f"<h1>{name}</h1>", INDEX, count=1)
    return BIO.sub(lambda m: f'<p class="bio">{bio}</p>', page, count=1)


def layout(title, body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{title}</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/style.css">
</head><body><main>{body}</main></body></html>"""


def login_page(error=""):
    msg = f'<p class="error" role="alert">{error}</p>' if error else ""
    return layout("Admin login", f"""<h1>Admin login</h1>{msg}
<form class="form" method="post" action="/admin">
<label for="pw">Password</label>
<input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>
<button>Log in</button>
</form><p><a href="/">Back to the page</a></p>""")


def admin_page(msg="", name=None, bio=None):
    with lock:
        rows = [("Page views", totals(counts.get("views", {})))]
        rows += [(label, totals(counts.get("clicks", {}).get(url, {}))) for url, label in LINKS]
        name = profile["name"] if name is None else name
        bio = profile["bio"] if bio is None else bio
    body = "".join(f'<tr><th scope="row">{html.escape(label)}</th>' + "".join(f"<td>{n}</td>" for n in t) + "</tr>"
                   for label, t in rows)
    return layout("Views", f"""<h1>Views</h1>
<table><thead><tr><td></td><th scope="col">Today</th><th scope="col">7 days</th><th scope="col">30 days</th>
<th scope="col">All time</th></tr></thead><tbody>{body}</tbody></table>
<p class="bio">Button rows are taps. Not counted: bots and link previews, your own visits while logged in,
a phone reloading within 5 minutes, and taps in Firefox or Brave (they don't report them).</p>
<h2 id="text">Page text</h2>{msg}
<form class="form" method="post" action="/admin/profile">
<label for="name">Name</label>
<input id="name" name="name" maxlength="60" required value="{html.escape(name)}">
<label for="bio">Bio (up to 4 lines)</label>
<textarea id="bio" name="bio" rows="3" maxlength="300">{html.escape(bio)}</textarea>
<button>Save</button>
</form>
<p><a href="/">Back to the page</a> · <a href="/admin/logout">Log out</a></p>""")


class Handler(SimpleHTTPRequestHandler):
    no_store = False

    def send_head(self):
        if self.headers.get("Host", "").lower().startswith("www."):
            return self.reply(301, location="https://ourobrs.dev" + self.path)
        path = urlsplit(self.path).path
        if path == "/admin":
            if not PASSWORD:
                return self.reply(503, layout("Admin", "<h1>Admin isn't set up</h1>"
                                              '<p class="bio">Add ADMIN_PASSWORD to .env on the Blade.</p>'))
            return self.reply(200, admin_page() if self.is_admin() else login_page())
        if path == "/admin/logout":
            return self.reply(303, location="/", cookie="admin=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict")
        if path in ("/", "/index.html"):
            if self.command == "GET" and self.countable():
                bump("views")
            return self.reply(200, index_page(), cache=True)
        return super().send_head()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 8192:
            return self.send(413)
        body = self.rfile.read(length)
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
        path = urlsplit(self.path).path
        if path == "/click":  # the <a ping="/click"> request a browser sends when a button is tapped
            to = self.headers.get("Ping-To")
            if any(to == url for url, _ in LINKS) and self.countable():
                bump("clicks", to)
            return self.send(204)
        if path == "/admin" and PASSWORD:
            return self.login(form.get("password", [""])[0])
        if path == "/admin/profile":
            if not self.is_admin():  # the cookie is SameSite=Strict, so other sites can't post this for you
                return self.send(403, login_page("Log in again to save."))
            return self.save_profile(form.get("name", [""])[0].strip(),
                                     form.get("bio", [""])[0].replace("\r\n", "\n").strip())
        self.send(404)

    def save_profile(self, name, bio):
        error = ("Name can't be empty." if not name else "Name is over 60 characters." if len(name) > 60 else
                 "Name must be one line." if "\n" in name else "Bio is over 300 characters." if len(bio) > 300 else
                 "Bio is over 4 lines." if bio.count("\n") > 3 else "")
        if not error:
            with lock:
                try:
                    save(PROFILE, {"name": name, "bio": bio})
                    profile.update(name=name, bio=bio)
                except OSError as e:
                    print("profile not saved:", e, file=sys.stderr)
                    error = "Couldn't save on the Blade. Nothing changed."
        if error:
            return self.send(400, admin_page(f'<p class="error" role="alert">{error}</p>', name, bio))
        self.send(200, admin_page('<p class="bio" role="status">Saved. Phones that opened the page in the '
                                  'last 5 minutes see it after reloading.</p>'))

    def login(self, password):
        ip = self.headers.get("CF-Connecting-IP", self.client_address[0])  # set by Cloudflare: all traffic comes through the tunnel
        now = time.time()
        with lock:
            for k in [k for k, v in fails.items() if now - v[-1] > 900]:
                del fails[k]
            recent = [t for t in fails.get(ip, []) if now - t < 900]
            if len(recent) >= 7:
                return self.send(429, login_page("Too many wrong tries. Wait 15 minutes."))
            if not hmac.compare_digest(password.encode(), PASSWORD.encode()):
                fails[ip] = recent + [now]
                return self.send(401, login_page("Wrong password."))
        exp = str(int(now) + MONTH)
        self.send(303, location="/admin",
                  cookie=f"admin={exp}.{sign(exp)}; Max-Age={MONTH}; Path=/; HttpOnly; Secure; SameSite=Strict")

    def is_admin(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "admin" and PASSWORD:
                exp, _, sig = value.partition(".")
                return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, sign(exp))
        return False

    def countable(self):
        ua = self.headers.get("User-Agent", "")
        return bool(ua) and not BOTS.search(ua) and not self.is_admin()

    def reply(self, status, body="", location=None, cookie=None, cache=False):
        data = body.encode()
        self.no_store = not cache
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if location:
            self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        return io.BytesIO(data)

    def send(self, *args, **kwargs):
        self.wfile.write(self.reply(*args, **kwargs).getvalue())

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; form-action 'self'")
        # pages: short, so edits show within 5 min even through Cloudflare; admin and counters: never cached
        self.send_header("Cache-Control", "no-store" if self.no_store else "public, max-age=300")
        super().end_headers()

    def log_message(self, *args):
        pass  # no access logs, and nothing piles up on the eMMC


ThreadingHTTPServer(("", PORT), partial(Handler, directory=SRV)).serve_forever()
