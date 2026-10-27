# ourobrs.dev link page

The link-in-bio page the mini turrets' QR codes point to (`https://ourobrs.dev`, printed into the
plastic, so keep that address working). It's plain HTML and CSS with no JavaScript and no build step.
A small Python server counts views and button taps for the admin page.

- `public/`: the website itself (`index.html`, `style.css`, `avatar.jpg`, `favicon.svg`)
- `serve.py`, `docker-compose.yml`: how the ZimaBlade serves it. Same idea as lss-photos, but its own folder,
  containers and tunnel, so it never touches lss-photos. `serve.py` also runs the counters and `/admin`.
- `test_serve.py`: checks the counters, login and text editing on this PC. Run `python test_serve.py` after changing
  `serve.py`; it prints `ok`.
- `deploy.sh`: copies everything to `/mnt/Seagate/ourobrs` on the Blade and restarts the site

## Edit

Everything is in `public/index.html`:

- **Links:** the `LINKS` list. Each `<li>` line is one button, top to bottom. Copy a line to add one, and
  keep its `ping="/click"`: that's what counts the taps. New buttons show up on the admin page by themselves.
- **Name and bio:** easiest from the admin page (**Page text**, under the view counts). It's live as soon as
  you save. The saved text lives on the Blade in `data/profile.json`, so `./deploy.sh` never undoes it, and it
  wins over the `PROFILE` block in `index.html`. To go back to the file's text, delete `data/profile.json` on
  the Blade and run `./deploy.sh`.
- **Photo:** the `PROFILE` block just above the links.
- **Link previews** (what a shared link shows in Discord, iMessage and so on): `<title>` and the
  `description` / `og:` lines at the top. Keep them in step with the handle and bio.
- **New photo:** save it as `public/avatar.jpg`, square, about 400×400 and under 100 KB.
- **Colours:** the `:root` block at the top of `public/style.css`.

Preview before you deploy: open `public/index.html` in a browser, or run
`python -m http.server 8765 --directory public` and go to http://localhost:8765.

## Redeploy

From Git Bash, in this folder:

```sh
./deploy.sh
```

Live within seconds. Phones that visited before keep the old page for up to 5 minutes, and the old
`style.css` or photo for up to 4 hours: Cloudflare tells browsers to keep files that long. For 5 minutes on
those too, set Cloudflare → ourobrs.dev → Caching → Configuration → Browser Cache TTL to "Respect Existing
Headers". Or save a new photo under a new name (`avatar2.jpg`) and update both `avatar` references in `index.html`.

## Admin: view counts

Tap **Admin login** at the bottom of the page (or go to https://ourobrs.dev/admin) and enter the admin
password. It shows page views and taps on each button for today, the last 7 and 30 days, and all time,
with days in US Eastern time, and lets you change the name and bio at the top of the page. You stay logged in for 30 days on that device.

- **Set or change the password:** on the Blade, edit `/mnt/Seagate/ourobrs/.env`, add or change the
  `ADMIN_PASSWORD=...` line, then run `./deploy.sh`. Changing it logs every device out. Without that line,
  `/admin` says it isn't set up.
- **Not counted:** bots and link previews, your own visits while you're logged in, a phone reloading within
  5 minutes, and taps from Firefox and Brave, which turn off the browser feature (`ping`) that reports them.
- **Privacy:** only daily totals are stored, in `/mnt/Seagate/ourobrs/data/counts.json`. There are no IPs, no
  visitor cookies and no third parties. After 10 wrong passwords from one IP in 15 minutes, that IP can't log in
  for 15 minutes; failed-login IPs are kept in memory only.
- **Reset the counts:** delete `data/counts.json` on the Blade, then `./deploy.sh`. Copy it somewhere first if
  you want to keep the history.

## How it's hosted (one-time setup, already done)

```
phone → https://ourobrs.dev → Cloudflare (HTTPS certificate) → tunnel → ZimaBlade: cloudflared → serve.py (site)
```

- **Cloudflare:** ourobrs.dev's DNS is on the same Cloudflare account as lss.photos.
  Zero Trust → Networks → Tunnels has a tunnel for this site, with two public hostnames:
  `ourobrs.dev` and `www.ourobrs.dev`, both type `HTTP`, URL `site:8000`. Those two hostnames create
  the DNS records themselves. Don't add A or AAAA records by hand.
- **Blade:** everything is in `/mnt/Seagate/ourobrs` on the Seagate drive. The containers use the
  `python:3.12-slim` and `cloudflared` images that lss-photos already pulled, so nothing new is stored on the eMMC.
  `.env` there holds `TUNNEL_TOKEN=...` and `ADMIN_PASSWORD=...` (`chmod 600`). It's not in this project and
  should never go in git. The counts are in `data/` next to it.
- **www** redirects to the bare domain in `serve.py`.

## If it breaks

- **502 / "Bad gateway" from Cloudflare:** the `site` container is down, or a public hostname's
  service isn't `HTTP` → `site:8000`. On the Blade: `cd /mnt/Seagate/ourobrs && sudo docker compose ps`.
- **Cloudflare error 1033:** the tunnel container isn't connected. Run `sudo docker compose logs tunnel`
  and look for "Registered tunnel connection".
- **`ssh` asks for a password:** your SSH key isn't on the Blade (see the key setup in the chat log,
  or copy `~/.ssh/id_ed25519.pub` into the Blade's `~/.ssh/authorized_keys`).
