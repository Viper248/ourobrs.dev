# Checks serve.py's counting and admin login on this PC: python test_serve.py (prints "ok")
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PHONE = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}
TIKTOK = "https://www.tiktok.com/@0urobrs"


def start(port, password, data=None):
    data = data or tempfile.mkdtemp()
    env = dict(os.environ, SRV=os.path.join(HERE, "public"), DATA=data, PORT=str(port), ADMIN_PASSWORD=password)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "serve.py")], env=env)
    for _ in range(50):
        try:
            http.client.HTTPConnection("127.0.0.1", port).connect()
            return proc, os.path.join(data, "counts.json")
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server didn't start")


def req(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode()


def saved(path):
    with open(path) as f:
        return json.load(f)


proc, counts = start(8771, "test-pw")
try:
    P = 8771
    assert req(P, "GET", "/", PHONE)[0] == 200
    req(P, "GET", "/", {"User-Agent": "Discordbot/2.0"})
    req(P, "HEAD", "/", PHONE)
    req(P, "GET", "/style.css", PHONE)
    assert sum(saved(counts)["views"].values()) == 1  # only the phone's GET of the page

    ping = dict(PHONE, **{"Ping-To": TIKTOK, "Content-Type": "text/ping"})
    assert req(P, "POST", "/click", ping, "PING")[0] == 204
    req(P, "POST", "/click", dict(ping, **{"Ping-To": "https://evil.example/"}), "PING")
    assert list(saved(counts)["clicks"]) == [TIKTOK]  # only real buttons get a counter

    s, h, body = req(P, "GET", "/admin", PHONE)
    assert s == 200 and 'type="password"' in body and h["Cache-Control"] == "no-store"
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    assert req(P, "POST", "/admin", form, "password=nope")[0] == 401
    s, h, _ = req(P, "POST", "/admin", form, "password=test-pw")
    assert s == 303 and h["Set-Cookie"].startswith("admin=") and "HttpOnly" in h["Set-Cookie"]
    me = dict(PHONE, Cookie=h["Set-Cookie"].split(";")[0])

    s, h, body = req(P, "GET", "/admin", me)
    assert s == 200 and "Page views" in body and "<th scope=\"row\">TikTok</th><td>1</td>" in body
    req(P, "GET", "/", me)
    req(P, "POST", "/click", dict(me, **{"Ping-To": TIKTOK}), "PING")
    assert sum(saved(counts)["views"].values()) == 1 and sum(saved(counts)["clicks"][TIKTOK].values()) == 1  # admin not counted

    forged = dict(PHONE, Cookie="admin=9999999999.deadbeef")
    assert 'type="password"' in req(P, "GET", "/admin", forged)[2]

    attacker = dict(form, **{"CF-Connecting-IP": "203.0.113.9"})
    assert [req(P, "POST", "/admin", attacker, "password=x")[0] for _ in range(11)] == [401] * 10 + [429]
    assert req(P, "POST", "/admin", attacker, "password=test-pw")[0] == 429  # locked even with the right password
    assert req(P, "POST", "/admin", form, "password=test-pw")[0] == 303  # other IPs still fine

    assert req(P, "POST", "/click", {"Content-Length": "5000"})[0] == 413
    assert req(P, "GET", "/", {"Host": "www.ourobrs.dev"})[1]["Location"] == "https://ourobrs.dev/"
    assert req(P, "GET", "/serve.py")[0] == 404
finally:
    proc.kill()

proc, _ = start(8772, "", data=os.path.join(HERE, "no-such-dir"))
try:
    assert req(8772, "GET", "/", PHONE)[0] == 200  # counts can't be saved: the page still loads
    assert req(8772, "GET", "/admin")[0] == 503  # no password set: admin is off
    assert req(8772, "POST", "/admin", {"Content-Type": "application/x-www-form-urlencoded"}, "password=")[0] == 404
finally:
    proc.kill()
print("ok")
