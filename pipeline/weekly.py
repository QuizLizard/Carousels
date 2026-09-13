#!/usr/bin/env python3
"""
Quiz Lizard weekly social automation.

Queues a week of Buffer drafts from carousels already on disk, then tops the
pool up by rendering more. Deterministic - no AI in the loop.

Order matters: queueing happens FIRST and never depends on rendering.
A render failure leaves the drafts intact and only fails the job at the end.

Credentials come from a .env file beside this script (never commit it):

    FEED_URL=https://<project>.supabase.co/functions/v1/automation-feed
    AUTOMATION_API_TOKEN=<token from Lovable>
    BUFFER_TOKEN=<buffer api key>

Usage:
    python weekly.py            # queue 7 days of drafts, then top up the pool
    python weekly.py --dry-run  # report what it would do, change nothing
    python weekly.py --render-only
    python weekly.py --queue-only
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
RENDER_BATCH_QUESTIONS = 48    # 12 carousels; endpoint caps limit at 50

DRY = "--dry-run" in sys.argv

# Collected and reported at the end. Non-empty means exit code 1.
PROBLEMS = []


def problem(msg):
    print(f"  !! {msg}")
    PROBLEMS.append(msg)


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
    # Only BUFFER_TOKEN is needed to queue. The feed secrets are needed to
    # render, and a missing one must not stop this week's drafts going out.
    if not cfg["BUFFER_TOKEN"]:
        sys.exit("Missing BUFFER_TOKEN. Set it as a GitHub secret, "
                 f"or in {envfile} for local runs.")
    return cfg


def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} calling {url}\n{e.read().decode()[:600]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach {url}: {e.reason}")


def post_json(url, payload, headers):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} calling {url}\n{e.read().decode()[:600]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach {url}: {e.reason}")


def feed_get(cfg, resource, limit=None):
    url = f"{cfg['FEED_URL']}?resource={resource}"
    if limit:
        url += f"&limit={limit}"
    data = get_json(url, {"x-automation-token": cfg["AUTOMATION_API_TOKEN"]})
    # endpoint wraps rows: {"resource":..., "count":N, "candidates":[...]}
    if isinstance(data, dict):
        return data.get("candidates", data.get("data", []))
    return data


def feed_mark(cfg, ids):
    if DRY or not ids:
        print(f"    [dry-run] would mark {len(ids)} questions used")
        return
    post_json(cfg["FEED_URL"], {"resource": "mark-posted", "ids": ids},
              {"x-automation-token": cfg["AUTOMATION_API_TOKEN"],
               "Content-Type": "application/json"})


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


def tiktok_title(caption):
    """First clause of the hook, capped at 80 chars.

    Splitting on '.' breaks on answers containing a full stop (S.Pellegrino,
    W.B. Yeats), so cut at the sentence boundary '. ' instead and fall back to
    a clean truncation.
    """
    head = caption.split(". ")[0].strip()
    if not head or len(head) > 80:
        head = caption[:80].rsplit(" ", 1)[0]
    return head[:80] or "Quiz Lizard"


class Enum(str):
    """Marks a value that must appear unquoted in GraphQL (e.g. an enum)."""


def gql(v):
    """Serialise a Python value as a GraphQL literal.
    Object keys are unquoted, strings are quoted, Enum values are raw."""
    if isinstance(v, Enum):
        return str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(gql(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {gql(x)}" for k, x in v.items()) + "}"
    if v is None:
        return "null"
    raise TypeError(f"cannot serialise {type(v)}")


def buffer_post(cfg, channel, folder, ratio, caption, title=None):
    """Create one draft. Returns the post dict, or raises RuntimeError."""
    alts = alt_lines(folder)
    assets = []
    for i in range(1, 10):
        n = f"{i:02d}"
        assets.append({"image": {
            "url": f"{RAW}/{folder}/{folder}_{ratio}_{n}.jpg",
            "metadata": {"altText": alts.get(n, f"Quiz Lizard carousel slide {i}")}}})

    inp = {"text": caption, "channelId": channel, "assets": assets,
           "schedulingType": Enum("automatic"), "mode": Enum("addToQueue"),
           "saveToDraft": True}
    if ratio == "9x16":
        inp["metadata"] = {"tiktok": {"title": title or "Quiz Lizard"}}
    else:
        inp["metadata"] = {"instagram": {"type": Enum("post"), "shouldShareToFeed": True}}

    query = ("mutation CreatePost { createPost(input: " + gql(inp) + ")"
             " { ... on PostActionSuccess { post { id status } }"
             "   ... on MutationError { message } } }")

    if DRY:
        print(f"    [dry-run] would create {ratio} draft for {folder}")
        return {"id": "dry-run"}

    res = post_json("https://api.buffer.com", {"query": query},
                    {"Authorization": f"Bearer {cfg['BUFFER_TOKEN']}",
                     "Content-Type": "application/json"})
    if res.get("errors"):
        raise RuntimeError(f"Buffer rejected {folder} ({ratio}): "
                           + json.dumps(res["errors"])[:400])
    payload = (res.get("data") or {}).get("createPost") or {}
    if payload.get("message"):
        raise RuntimeError(f"Buffer error on {folder} ({ratio}): {payload['message']}")
    return payload.get("post", {})


def git(*args):
    if DRY:
        print(f"    [dry-run] git {' '.join(args)}")
        return
    subprocess.run(["git", "-C", str(REPO), *args], check=True)


def queue_week(cfg, remaining):
    """Create drafts for up to a week of carousels. Returns the last folder
    fully queued on both channels, or None if nothing was queued."""
    batch = remaining[:CAROUSELS_PER_WEEK]
    if not batch:
        problem("Nothing left to queue - the carousel pool is empty.")
        return None
    if len(batch) < CAROUSELS_PER_WEEK:
        problem(f"Only {len(batch)} carousels available, wanted {CAROUSELS_PER_WEEK}. "
                "Approve more questions in the admin swipe review.")

    last_ok = None
    for folder in batch:
        cap_tt = read_local(folder, "caption_tiktok.txt")
        cap_ig = read_local(folder, "caption_instagram.txt")
        if not cap_tt or not cap_ig:
            problem(f"{folder}: skipped - missing caption file")
            continue
        print(f"  {folder}")
        try:
            buffer_post(cfg, TIKTOK_CHANNEL, folder, "9x16", cap_tt, tiktok_title(cap_tt))
            buffer_post(cfg, INSTAGRAM_CHANNEL, folder, "4x5", cap_ig)
        except RuntimeError as e:
            # One bad folder (or a full draft queue) must not cost the rest.
            problem(str(e))
            continue
        last_ok = folder

    return last_ok


def render_more(cfg):
    """Top the pool up. Returns new folder names. Never raises."""
    if not cfg.get("FEED_URL") or not cfg.get("AUTOMATION_API_TOKEN"):
        problem("Skipping render: FEED_URL or AUTOMATION_API_TOKEN is not set.")
        return []
    print("Rendering a new batch...")
    try:
        rows = feed_get(cfg, "social-candidates", RENDER_BATCH_QUESTIONS)
    except RuntimeError as e:
        problem(f"Feed unreachable, pool not topped up: {e}")
        return []
    if not rows:
        problem("No approved questions left. Swipe more in the admin panel.")
        return []

    data, ids = [], []
    try:
        for r in rows:
            bd = r["breakdown"] if isinstance(r["breakdown"], list) else json.loads(r["breakdown"])
            bd = sorted(bd, key=lambda b: -int(b["pct"]))
            data.append([r["question_text"],
                         [[b["option"], int(b["pct"]), bool(b["is_correct"])] for b in bd]])
            ids.append(r["question_id"])
    except (KeyError, ValueError, TypeError) as e:
        problem(f"Feed returned rows this script cannot read: {e}")
        return []

    qfile = HERE / "questions.json"
    qfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = folders()
    start = int(before[-1][1:]) if before else 0
    if not DRY:
        try:
            subprocess.run([sys.executable, str(HERE / "build.py"),
                            str(qfile), str(start), str(REPO)], check=True)
        except subprocess.CalledProcessError as e:
            problem(f"build.py failed ({e.returncode}), pool not topped up.")
            return []

    new = [f for f in folders() if int(f[1:]) > start]
    if not new:
        problem("build.py produced no new carousels.")
        return []
    try:
        feed_mark(cfg, ids)
    except RuntimeError as e:
        problem(f"Rendered {len(new)} carousels but could not mark questions used: {e}")
    return new


def main():
    cfg = env()
    all_folders = folders()
    if not all_folders:
        sys.exit(f"No carousel folders found in {REPO}")

    last = state_get()["last_scheduled_carousel"]
    remaining = [f for f in all_folders if int(f[1:]) > int(last[1:])]
    print(f"{len(all_folders)} carousels on disk, last queued {last}, "
          f"{len(remaining)} unqueued")

    # ---- 1. Queue this week. Nothing above can stop this. ----
    if "--render-only" not in sys.argv:
        queued_to = queue_week(cfg, remaining)
        if queued_to:
            state_set(queued_to)
            n = remaining.index(queued_to) + 1
            print(f"Queued {n} carousels as drafts, through {queued_to}.")
            print("Review and promote them in Buffer before they publish.")
            remaining = remaining[n:]

    # ---- 2. Top the pool up. Failures here are reported, not fatal. ----
    if "--queue-only" not in sys.argv and len(remaining) < MIN_BUFFER_FOLDERS:
        new = render_more(cfg)
        if new:
            try:
                git("add", "-A")
                git("commit", "-m", f"Add carousels {new[0]}-{new[-1]}")
                git("push")
                print(f"  pushed {len(new)} new carousels")
            except subprocess.CalledProcessError as e:
                problem(f"Rendered {len(new)} carousels but git push failed: {e}")

    print(f"\n{len(remaining)} carousels will remain unqueued after this week.")
    if PROBLEMS:
        print(f"\nFinished with {len(PROBLEMS)} problem(s):")
        for p in PROBLEMS:
            print(f"  - {p}")
        sys.exit(1)


if __name__ == "__main__":
    main()
