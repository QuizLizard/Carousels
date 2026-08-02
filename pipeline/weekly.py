#!/usr/bin/env python3
"""
Quiz Lizard weekly social automation.

Renders any needed carousels, pushes them, and queues a week of Buffer drafts.
Deterministic - no AI in the loop. Intended to run from Windows Task Scheduler.

Credentials come from a .env file beside this script (never commit it):

    FEED_URL=https://<project>.supabase.co/functions/v1/automation-feed
    AUTOMATION_API_TOKEN=<token from Lovable>
    BUFFER_TOKEN=<buffer api key>

Usage:
    python weekly.py            # render if needed, push, queue 7 days of drafts
    python weekly.py --dry-run  # report what it would do, change nothing
    python weekly.py --render-only
"""
import os, sys, json, subprocess, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RAW = "https://raw.githubusercontent.com/QuizLizard/Carousels/main"

TIKTOK_CHANNEL = "69cc4db1af47dacb6975e593"
INSTAGRAM_CHANNEL = "68fff718669affb4c98b8324"

CAROUSELS_PER_WEEK = 7
MIN_BUFFER_FOLDERS = 14        # render more when fewer than this remain unqueued
RENDER_BATCH_QUESTIONS = 80    # 20 carousels

DRY = "--dry-run" in sys.argv


def env():
    cfg = {}
    envfile = HERE / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    for k in ("FEED_URL", "AUTOMATION_API_TOKEN", "BUFFER_TOKEN"):
        cfg.setdefault(k, os.environ.get(k, ""))
        if not cfg[k]:
            sys.exit(f"Missing {k}. Set it as a GitHub secret, or in {envfile} for local runs.")
    return cfg


def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} calling {url}\n{e.read().decode()[:600]}")


def feed_get(cfg, resource, limit=None):
    url = f"{cfg['FEED_URL']}?resource={resource}"
    if limit:
        url += f"&limit={limit}"
    return get_json(url, {"x-automation-token": cfg["AUTOMATION_API_TOKEN"]})


def feed_mark(cfg, ids):
    if DRY or not ids:
        print(f"    [dry-run] would mark {len(ids)} questions used")
        return
    post_json(cfg["FEED_URL"], {"resource": "mark-posted", "ids": ids},
              {"x-automation-token": cfg["AUTOMATION_API_TOKEN"],
               "Content-Type": "application/json"})


def post_json(url, payload, headers):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} calling {url}\n{e.read().decode()[:600]}")


STATE = HERE / "state.json"


def state_get():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"last_scheduled_carousel": "c00"}


def state_set(folder):
    if not DRY:
        STATE.write_text(json.dumps({"last_scheduled_carousel": folder}, indent=1))


def folders():
    return sorted(p.name for p in REPO.iterdir()
                  if p.is_dir() and p.name.startswith("c") and p.name[1:].isdigit())


def read_local(folder, name):
    p = REPO / folder / name
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def alt_lines(folder):
    txt = read_local(folder, "alt_text.txt") or ""
    out = {}
    for line in txt.splitlines():
        if ": " in line:
            key, val = line.split(": ", 1)
            slide = key.strip().split("_")[-1]
            out[slide] = val.strip()
    return out


def buffer_post(cfg, channel, folder, ratio, caption, title=None):
    alts = alt_lines(folder)
    assets = []
    for i in range(1, 10):
        n = f"{i:02d}"
        assets.append({"image": {
            "url": f"{RAW}/{folder}/{folder}_{ratio}_{n}.jpg",
            "metadata": {"altText": alts.get(n, f"Quiz Lizard carousel slide {i}")}}})
    payload = {"channelId": channel, "text": caption, "assets": assets,
               "saveToDraft": True, "schedulingType": "automatic"}
    if ratio == "9x16":
        payload["metadata"] = {"tiktok": {"title": title or "Quiz Lizard"}}
    else:
        payload["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True}}
    if DRY:
        print(f"    [dry-run] would create {ratio} draft for {folder}")
        return {"id": "dry-run"}
    return post_json("https://api.bufferapp.com/2/updates/create.json", payload,
                     {"Authorization": f"Bearer {cfg['BUFFER_TOKEN']}",
                      "Content-Type": "application/json"})


def git(*args):
    if DRY:
        print(f"    [dry-run] git {' '.join(args)}")
        return
    subprocess.run(["git", "-C", str(REPO), *args], check=True)


def render_more(cfg):
    print("Rendering a new batch...")
    rows = feed_get(cfg, "social-candidates", RENDER_BATCH_QUESTIONS)
    if not rows:
        print("  No approved questions left. Swipe more in the admin panel.")
        return []
    data, ids = [], []
    for r in rows:
        bd = r["breakdown"] if isinstance(r["breakdown"], list) else json.loads(r["breakdown"])
        bd = sorted(bd, key=lambda b: -int(b["pct"]))
        data.append([r["question_text"],
                     [[b["option"], int(b["pct"]), bool(b["is_correct"])] for b in bd]])
        ids.append(r["question_id"])
    qfile = HERE / "questions.json"
    qfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    last = folders()[-1] if folders() else "c00"
    start = int(last[1:])
    if not DRY:
        subprocess.run([sys.executable, str(HERE / "build.py"),
                        str(qfile), str(start), str(REPO)], check=True)
    new = [f for f in folders() if int(f[1:]) > start]
    if new:
        feed_mark(cfg, ids)
    return new


def main():
    cfg = env()
    all_folders = folders()
    if not all_folders:
        sys.exit(f"No carousel folders found in {REPO}")

    last = state_get()["last_scheduled_carousel"]
    remaining = [f for f in all_folders if int(f[1:]) > int(last[1:])]
    print(f"{len(all_folders)} carousels on disk, last queued {last}, {len(remaining)} unqueued")

    if len(remaining) < MIN_BUFFER_FOLDERS:
        new = render_more(cfg)
        if new:
            git("add", "-A")
            git("commit", "-m", f"Add carousels {new[0]}-{new[-1]}")
            git("push")
            remaining += new
            print(f"  pushed {len(new)} new carousels")

    if "--render-only" in sys.argv:
        return

    batch = remaining[:CAROUSELS_PER_WEEK]
    if not batch:
        sys.exit("Nothing left to queue.")

    for folder in batch:
        cap_tt = read_local(folder, "caption_tiktok.txt")
        cap_ig = read_local(folder, "caption_instagram.txt")
        if not cap_tt or not cap_ig:
            print(f"  {folder}: SKIPPED - missing caption file")
            continue
        title = cap_tt.split(".")[0][:80]
        print(f"  {folder}")
        buffer_post(cfg, TIKTOK_CHANNEL, folder, "9x16", cap_tt, title)
        buffer_post(cfg, INSTAGRAM_CHANNEL, folder, "4x5", cap_ig)

    state_set(batch[-1])
    print(f"Queued {len(batch)} carousels as drafts, through {batch[-1]}.")
    print("Review and promote them in Buffer before they publish.")


if __name__ == "__main__":
    main()
