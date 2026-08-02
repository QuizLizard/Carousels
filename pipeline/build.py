#!/usr/bin/env python3
"""Chunk approved questions into 4-question carousels and render every one."""
import json, os, shutil, sys
SRC = sys.argv[1] if len(sys.argv) > 1 else "approved.json"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 0
OUT = sys.argv[3] if len(sys.argv) > 3 else "batch"
import render as R

PATTERNS = ["CADB", "BDAC", "ADBC", "DBCA", "CBDA"]
TAGS = "#trivia #quiz #pubquiz #triviaquiz"
BANDS = [["4/4  Top of the class!", "\U0001F9E0"],
         ["2-3  Not bad!", "\U0001F913"],
         ["0-1  Need more practice!", "\U0001F98E"]]


def round5(opts):
    """Round each share to the nearest 5 and force the set to total 100.
    Never adjusts the correct answer or the plurality pick if avoidable."""
    r = [5 * round(p / 5) for _, p, _ in opts]
    order = sorted(range(len(opts)), key=lambda i: -opts[i][1])
    plur = order[0]
    corr = next(i for i, o in enumerate(opts) if o[2])
    for _ in range(40):
        total = sum(r)
        if total == 100:
            break
        step = 5 if total < 100 else -5
        for pool in ([i for i in order if i not in (plur, corr)],
                     [i for i in order if i != corr],
                     list(order)):
            cands = [i for i in pool if r[i] + step >= 0]
            if cands:
                r[cands[0]] += step
                break
    return r


def to_spec(chunk, c_idx):
    # strongest trap last, second strongest first
    scored = []
    for q, opts in chunk:
        pcts = round5(opts)
        corr = next(i for i, o in enumerate(opts) if o[2])
        top_wrong = max(pcts[i] for i in range(4) if i != corr)
        scored.append((top_wrong - pcts[corr], q, opts, pcts, corr))
    scored.sort(key=lambda s: s[0])
    ordered = [scored[-2], scored[0], scored[1], scored[-1]] if len(scored) == 4 else scored

    questions = []
    for qi, (_, q, opts, pcts, corr) in enumerate(ordered):
        slot = PATTERNS[c_idx % len(PATTERNS)][qi]
        others = [i for i in sorted(range(4), key=lambda i: -pcts[i]) if i != corr]
        slots = {slot: corr}
        for L in [c for c in "ABCD" if c != slot]:
            slots[L] = others.pop(0)
        options = []
        for L in "ABCD":
            i = slots[L]
            options.append({"letter": L, "text": opts[i][0], "pct": pcts[i],
                            **({"correct": True} if i == corr else {})})
        cp = pcts[corr]
        questions.append({
            "question": q,
            "closing": "Nobody got this right" if cp == 0 else f"Only {cp}% got this right",
            "options": options})
    return {"slug": f"c{c_idx+1+START:02d}", "score_bands": BANDS, "questions": questions}



def alt_text(q, kind):
    if kind == "q":
        return f"Quiz question: {q['question']} Four options: " + \
               ", ".join(f"{o['letter']} {o['text']}" for o in q["options"])
    corr = next(o for o in q["options"] if o.get("correct"))
    return f"Answer slide. {q['question']} Correct answer: {corr['text']}, chosen by {corr['pct']} percent. " + \
           "Full vote: " + ", ".join(f"{o['text']} {o['pct']} percent" for o in q["options"])


def caption(spec):
    lead = spec["questions"][-1]           # strongest trap sits last
    corr = next(o for o in lead["options"] if o.get("correct"))
    wrong = max((o for o in lead["options"] if not o.get("correct")), key=lambda o: o["pct"])
    hook = f'{wrong["pct"]}% of players said "{wrong["text"]}".'
    if wrong["pct"] > corr["pct"]:
        hook += f' The answer is "{corr["text"]}".'
    else:
        hook += f' Only {corr["pct"]}% got it right.'
    body = (f'{hook} These are real votes from Quiz Lizard players. '
            f'Four questions in here \u2014 score out of 4 in the comments \U0001F447 '
            f'New set every day. Daily quiz at quizlizard.app')
    ig = body + "\n\n" + TAGS
    tt = body + " " + TAGS
    return ig, tt


data = json.load(open(SRC))
chunks = [data[i:i + 4] for i in range(0, len(data), 4)]
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
manifest = []

for c_idx, chunk in enumerate(chunks):
    if len(chunk) < 4:
        continue
    spec = to_spec(chunk, c_idx)
    d = f"{OUT}/{spec['slug']}"
    os.makedirs(d, exist_ok=True)
    json.dump(spec, open(f"{d}/spec.json", "w"), ensure_ascii=False, indent=1)
    R.render(f"{d}/spec.json", d)
    os.remove(f"{d}/spec.json")
    ig, tt = caption(spec)
    open(f"{d}/caption_instagram.txt", "w").write(ig)
    open(f"{d}/caption_tiktok.txt", "w").write(tt)
    alts = []
    for i, q in enumerate(spec["questions"], 1):
        alts.append(f"{spec['slug']}_*_{2*i-1:02d}: " + alt_text(q, "q"))
        alts.append(f"{spec['slug']}_*_{2*i:02d}: " + alt_text(q, "a"))
    alts.append(f"{spec['slug']}_*_09: Score guide. 4 out of 4 top of the class, "
                "2 to 3 not bad, 0 to 1 need more practice. Play the daily quiz at quizlizard.app")
    open(f"{d}/alt_text.txt", "w").write("\n".join(alts))
    manifest.append((spec["slug"], [q["question"] for q in spec["questions"]], spec))

print(f"{len(manifest)} carousels, {sum(len(os.listdir(OUT+'/'+m[0])) for m in manifest)} images")

# integrity pass
bad = 0
for slug, _, spec in manifest:
    for q in spec["questions"]:
        tot = sum(o["pct"] for o in q["options"])
        ncorr = sum(1 for o in q["options"] if o.get("correct"))
        if tot != 100 or ncorr != 1:
            print(f"  !! {slug}: total={tot} correct={ncorr} :: {q['question'][:50]}")
            bad += 1
print("integrity:", "all sets total 100 with exactly one correct answer" if not bad else f"{bad} PROBLEMS")

lines = ["# Carousel batch - 20 sets, 4 questions each", ""]
for slug, qs, spec in manifest:
    slots = "".join(o["letter"] for q in spec["questions"] for o in q["options"] if o.get("correct"))
    lines.append(f"## {slug}  (correct slots: {slots})")
    for i, q in enumerate(qs, 1):
        lines.append(f"{i}. {q}")
    lines.append("")
open(f"{OUT}/CONTENTS.md", "w").write("\n".join(lines))
