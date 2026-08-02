# Quiz Lizard carousel pipeline

Renders 9-slide carousels in both aspect ratios, plus captions and alt text, from a JSON list of questions with real player vote data.

## One-time setup

```bash
./setup.sh
```

Downloads Nunito and Noto Color Emoji into `fonts/` (gitignored — they're large and freely redownloadable) and installs Pillow.

## Rendering a batch

```bash
python3 build.py questions.json 38 ../
```

Three arguments:

1. **input JSON** — the questions (format below)
2. **start index** — the number of the last carousel already in the repo. Passing `38` makes the new folders start at `c39`. **Always append, never overwrite** — git stores every version of every binary forever, so re-rendering over existing filenames bloats the repo permanently.
3. **output directory** — `../` writes carousel folders to the repo root

Each carousel folder gets 18 JPEGs (9 at 4:5 for Instagram, 9 at 9:16 for TikTok), `caption_instagram.txt`, `caption_tiktok.txt` and `alt_text.txt`.

## Input format

A JSON array. Each entry is `[question_text, [[option_text, percent, is_correct], ...]]` with exactly four options:

```json
[
  ["Which country has the most people of Japanese descent, not including Japan?",
   [["United States of America", 76, false],
    ["Brazil", 14, true],
    ["South Korea", 5, false],
    ["China", 5, false]]]
]
```

Percentages are raw from the database. The build script rounds each to the nearest 5 and forces every set to total 100, adjusting the second-largest bucket rather than the correct answer or the plurality pick.

Questions are consumed four at a time in the order given.

## Getting the questions out of Supabase

```sql
SELECT jsonb_agg(jsonb_build_array(
         question_text,
         (SELECT jsonb_agg(jsonb_build_array(b->>'option', (b->>'pct')::int, (b->>'is_correct')::boolean)
                 ORDER BY (b->>'pct')::int DESC)
          FROM jsonb_array_elements(breakdown) b))
       ORDER BY margin DESC)
FROM (
  SELECT * FROM social_candidates
  WHERE review_status = 'approved' AND used_at IS NULL
  ORDER BY margin DESC, respondents DESC
  LIMIT 80
) s;
```

Then mark them consumed so they never repeat:

```sql
UPDATE social_candidates SET used_at = now()
WHERE question_id IN (...the ids just rendered...);
```

`refresh_social_candidates()` repopulates the pool from quiz history. Its `ON CONFLICT` clause deliberately preserves `review_status`, `reviewed_at` and `used_at` — refreshing must never wipe review decisions.

## What to check before publishing

**Perishable questions.** Anything phrased as a current record — largest, fastest, most locations, "as of 2025" — traps players precisely because the famous old answer is now wrong, which means the answer will change again. Verify these the week they post, not the week they render.

**Near-duplicates.** Two questions with the same answer in different words will read as a repeat if they land in the same fortnight.

**Ties.** When the top wrong answer and the correct answer are within a few points, the poll reads flat and the reveal has no punch.

## Layout

`render.py` holds the geometry in `LAYOUTS` — one entry per aspect ratio. Card positions, header size and the score-slide offsets are all numbers in that dict; nothing else needs touching to reposition elements.

Correct answers are highlighted two ways: the card fills with `#deeec3` and a green tick badge is drawn in the corner. The badge is vector-drawn rather than a font glyph because Nunito has no U+2713 — it renders as tofu.

## Publishing

Images are served from `https://raw.githubusercontent.com/QuizLizard/Carousels/main/<folder>/<file>` once pushed. Buffer fetches them by URL, so **the repo must stay public** — raw.githubusercontent.com won't serve from a private repo without auth, and posts fail silently.

---

# Weekly automation (`weekly.py`)

Runs the whole loop with no AI involved: renders if the buffer is low, pushes, and queues seven days of Buffer drafts.

## Setup

1. Create `pipeline/.env` (gitignored — never commit it):

```
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service role key>
BUFFER_TOKEN=<buffer api key>
```

Get the Supabase service role key from the project's API settings. Get the Buffer key from Buffer's developer settings — the free plan includes one key and 3,000 requests a month, against roughly 60 needed here.

2. Supabase has no generic SQL-over-REST endpoint, so add this helper once:

```sql
CREATE OR REPLACE FUNCTION public.exec_sql(statement text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE result jsonb;
BEGIN
  EXECUTE 'SELECT coalesce(jsonb_agg(t), ''[]''::jsonb) FROM (' || statement || ') t'
  INTO result;
  RETURN result;
EXCEPTION WHEN others THEN
  EXECUTE statement;
  RETURN '[]'::jsonb;
END; $$;
REVOKE ALL ON FUNCTION public.exec_sql(text) FROM anon, authenticated;
```

This is powerful — it runs arbitrary SQL as the definer. The REVOKE line matters: only the service role key should reach it, and that key must stay out of the repo and off the client.

3. Dry run first:

```bash
python weekly.py --dry-run
```

It reports what it would render and queue without touching anything. Only schedule it once that output looks right.

## Scheduling on Windows

Task Scheduler → Create Task → weekly, Sunday 09:00 → Action: start `python` with argument `C:\path\to\Carousels\pipeline\weekly.py`. Tick "Run whether user is logged on or not" if the machine stays on.

## What it does

- Reads `last_scheduled_carousel` from `app_config` to find its place
- If fewer than 14 unqueued carousel folders remain, pulls 80 approved questions, renders 20 new carousels, commits, pushes, and marks those questions used
- Creates 7 TikTok and 7 Instagram drafts from the next folders in sequence
- Advances `last_scheduled_carousel`

Drafts, never live posts. Promoting them in Buffer stays manual — it's the checkpoint where a stale "world's largest retailer" answer gets caught before it publishes.

## Verify before trusting it

The Buffer endpoint in this script (`api.bufferapp.com/2/updates/create.json`) needs checking against Buffer's current API docs. Their MCP connector uses a different internal path, and their public REST API has changed over time. `--dry-run` won't catch this — make one real call and confirm a draft appears before scheduling the task.
