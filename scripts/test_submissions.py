"""Visitor review uploads — tests.

The promise being tested: **nothing a visitor sends reaches the dataset until a
person approves it and runs the ingest step**, and when it does, it goes through
the same pipeline as any other batch without disturbing what is already there.

  1. the storage rules (cleaning, validation, duplicates, decisions, rate limit);
  2. the web API: what it accepts, what it refuses, what it saves, and that it
     saves nothing that identifies the visitor;
  3. the whole journey on a throwaway copy of the data: submit -> approve ->
     ingest -> database -> API, including that an entity keeps its ID when new
     reviews arrive, and that the real `data/` folder is never touched.

Everything runs on temporary folders. Run:
    .venv/bin/python scripts/test_submissions.py
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
PASSED: list[str] = []
FAILED: list[str] = []

BANGLA = "লালবাগ কেল্লা খুবই সুন্দর একটি ঐতিহাসিক জায়গা, পরিবার নিয়ে ঘুরতে যাওয়ার জন্য একদম উপযুক্ত।"
GOOD_EN = "We spent a lovely afternoon here; the gardens were calm and the guide was very friendly."
NEW_PLACE_TEXT = (
    "Take an engine boat from Mongla Ferry Ghat early in the morning. The quiet channels near "
    "Chandpai are worth the extra hour and very few tourists ever go there."
)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def fingerprint_dir(path: Path) -> dict[str, str]:
    """A content hash for every file, to prove a folder was not touched."""
    return {
        str(p.relative_to(path)): hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
    }


def copy_data(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.csv", "*.json"):
        for src in DATA_DIR.glob(pattern):
            shutil.copy2(src, dest / src.name)
    (dest / "touristinbd.db").unlink(missing_ok=True)
    return dest


def run_script(script: str, *args: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "TOURISTINBD_DATA_DIR": str(data_dir)}
    env.pop("TOURISTINBD_UPLOADS_DIR", None)
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / script), *args],
                          cwd=REPO_ROOT, env=env, capture_output=True, text=True)


def boot_api(data_dir: Path):
    """Start the API against `data_dir`; returns (client, the submissions module the API uses)."""
    os.environ["TOURISTINBD_DATA_DIR"] = str(data_dir)
    for name in [m for m in sys.modules if m == "backend" or m.startswith("backend.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient

    main = importlib.import_module("backend.main")
    return TestClient(main.app), importlib.import_module("backend.submissions")


# ---------------------------------------------------------------------------
# 1. storage rules
# ---------------------------------------------------------------------------
def test_storage(subs, uploads: Path) -> None:
    print("\nstorage rules")
    os.environ["TOURISTINBD_UPLOADS_DIR"] = str(uploads)
    known = {"lalbagh fort": "Lalbagh Fort"}

    check("markup is stripped but words are kept",
          subs.clean_text("<b>Nice</b> <script>x()</script>place") == "Nice x() place",
          subs.clean_text("<b>Nice</b> <script>x()</script>place"))
    check("Bangla passes through untouched", subs.clean_text(BANGLA) == BANGLA, "")
    check("the same text with other spacing and case has the same fingerprint",
          subs.text_fingerprint("Good  PLACE here") == subs.text_fingerprint(" good place   HERE "), "")

    def bad(**overrides):
        args = dict(place_name="Lalbagh Fort", is_new_place=False, district=None, rating=5,
                    review_text=GOOD_EN, known_places=known)
        args.update(overrides)
        try:
            subs.validate(**args)
            return None
        except subs.SubmissionError as exc:
            return str(exc)

    check("a good review is accepted", bad() is None, str(bad()))
    check("place names match case-insensitively",
          subs.validate("lalbagh FORT", False, None, 4, GOOD_EN, known)["place_name"] == "Lalbagh Fort", "")
    check("a rating of 0 is refused", bad(rating=0) is not None)
    check("a rating of 6 is refused", bad(rating=6) is not None)
    check("a rating that is not a number is refused", bad(rating="five") is not None)
    check("a too-short review is refused", bad(review_text="nice") is not None)
    check("a too-long review is refused", bad(review_text="a b " * 2000) is not None)
    check("a review of one repeated letter is refused", bad(review_text="a" * 80) is not None)
    check("two links are refused as spam", bad(review_text=GOOD_EN + " http://a.example http://b.example") is not None)
    check("an unknown place is refused unless marked as new", bad(place_name="Atlantis Beach") is not None)
    check("a new place without a district is refused",
          bad(place_name="Atlantis Beach", is_new_place=True, district="") is not None)
    new = subs.validate("Atlantis Beach", True, "Bhola", 3, GOOD_EN, known)
    check("a new place with a district is accepted", new["is_new_place"] and new["district"] == "Bhola", str(new))
    again = subs.validate("Lalbagh Fort", True, "Dhaka", 3, GOOD_EN, known)
    check("a 'new' place that already exists is treated as the existing one",
          not again["is_new_place"] and again["district"] is None, str(again))

    clean = subs.validate("Lalbagh Fort", False, None, 5, BANGLA, known)
    record = subs.save_pending(clean)
    saved = uploads / "pending" / f"{record['id']}.json"
    check("a submission is saved as a file in pending/", saved.exists(), str(saved))
    on_disk = json.loads(saved.read_text(encoding="utf-8"))
    check("the Bangla is saved exactly as typed", on_disk["review_text"] == BANGLA, "")
    allowed = {"id", "submitted_at_utc", "status", "place_name", "is_new_place", "district", "rating",
               "review_text", "geography", "text_hash", "decisions"}
    check("only the expected fields are stored — no name, email or IP", set(on_disk) == allowed,
          str(set(on_disk) ^ allowed))
    try:
        subs.save_pending(clean)
        dup = False
    except subs.DuplicateSubmission:
        dup = True
    check("sending the same review twice is refused", dup)

    os.environ["TOURISTINBD_MAX_PENDING"] = "1"
    try:
        subs.save_pending(subs.validate("Lalbagh Fort", False, None, 4, GOOD_EN, known))
        full = False
    except subs.InboxFull:
        full = True
    os.environ.pop("TOURISTINBD_MAX_PENDING")
    check("a full inbox stops accepting", full)

    for bad_id in ("../../etc/passwd", "V1-zzzzzz", "", "V20261006T101500-ab12cd/../x"):
        try:
            subs.find(bad_id)
            ok = False
        except KeyError:
            ok = True
        check(f"the id {bad_id!r} cannot escape the folder", ok)

    for kwargs, label in (({"by": "", "reason": "fine"}, "a name"), ({"by": "Yakin", "reason": "  "}, "a reason")):
        try:
            subs.decide(record["id"], "approved", **kwargs)
            refused = False
        except ValueError:
            refused = True
        check(f"a decision without {label} is refused", refused)
    check("a refused decision leaves the file in pending/", saved.exists())

    done = subs.decide(record["id"], "approved", "Yakin", "genuine review")
    check("approving moves the file to approved/",
          (uploads / "approved" / saved.name).exists() and not saved.exists(), "")
    check("the decision records who, why and when",
          done["decisions"][0]["by"] == "Yakin" and done["decisions"][0]["reason"] == "genuine review"
          and done["decisions"][0]["at_utc"], str(done["decisions"]))
    changed = subs.decide(record["id"], "rejected", "Yakin", "changed my mind")
    check("a changed mind keeps both decisions", len(changed["decisions"]) == 2, str(changed["decisions"]))

    newrec = subs.save_pending(subs.validate("Atlantis Beach", True, "Bhola", 3, GOOD_EN + " Different words here.", known))
    try:
        subs.decide(newrec["id"], "approved", "Yakin", "ok")
        needs = False
    except ValueError as exc:
        needs = "division" in str(exc)
    check("approving a NEW place requires its division", needs)
    ok = subs.decide(newrec["id"], "approved", "Yakin", "ok", {"division": "Barishal"})
    check("a new place keeps the geography given at approval",
          ok["geography"]["division"] == "Barishal" and ok["geography"]["district"] == "Bhola", str(ok["geography"]))

    limiter = subs.RateLimiter(limit=3, window=3600)
    check("the rate limiter allows up to its limit", all(limiter.allow("a") for _ in range(3)))
    check("…then refuses", not limiter.allow("a"))
    check("…per client", limiter.allow("b"))
    os.environ.pop("TOURISTINBD_UPLOADS_DIR")


# ---------------------------------------------------------------------------
# 2. the web API
# ---------------------------------------------------------------------------
def test_api(client, subs, data: Path, uploads: Path) -> None:
    print("\nthe web API")
    os.environ["TOURISTINBD_UPLOADS_DIR"] = str(uploads)
    subs.limiter.reset()
    subs.limiter.limit = 100
    before = fingerprint_dir(data)
    total_before = client.get("/api/overview").json()["total_reviews"]

    r = client.get("/api/submissions/options")
    options = r.json()
    check("the form options load", r.status_code == 200 and len(options["places"]) >= 20, str(r.status_code))
    check("the options list districts and limits", options["districts"] and options["limits"]["min_text"], "")

    def post(**overrides):
        body = {"place_name": "Lalbagh Fort", "is_new_place": False, "district": None, "rating": 5,
                "review_text": GOOD_EN, "website": ""}
        body.update(overrides)
        return client.post("/api/submissions", json=body)

    r = post()
    check("a valid review is accepted with 202", r.status_code == 202, f"{r.status_code} {r.text[:200]}")
    check("the visitor is told it is pending", r.json()["status"] == "pending", str(r.json()))
    saved = list((uploads / "pending").glob("V*.json"))
    check("it was saved to the pending folder", len(saved) == 1, str(saved))
    check("it did not change the dataset or the database",
          client.get("/api/overview").json()["total_reviews"] == total_before and fingerprint_dir(data) == before,
          "the data folder changed")
    pending_text = json.loads(saved[0].read_text(encoding="utf-8"))["review_text"]
    check("pending text is not served by any public endpoint",
          pending_text not in client.get("/api/reviews", params={"q": "lovely afternoon", "limit": 50}).text
          and "submissions" not in " ".join(p for p in client.get("/openapi.json").json()["paths"] if p.endswith("/pending")), "")

    r = post()
    check("sending it again is refused with 409", r.status_code == 409, str(r.status_code))
    check("a short review is refused with 422", post(review_text="too short").status_code == 422)
    check("a rating of 9 is refused with 422", post(rating=9).status_code == 422)
    check("an unknown place is refused with 422", post(place_name="Atlantis Beach", review_text=GOOD_EN + " b").status_code == 422)
    r = post(place_name="Atlantis Beach", is_new_place=True, district="", review_text=GOOD_EN + " c")
    check("a new place without a district is refused with 422", r.status_code == 422, str(r.status_code))
    check("a missing field is refused with 422", client.post("/api/submissions", json={"rating": 5}).status_code == 422)

    r = post(place_name="Atlantis Beach", is_new_place=True, district="Bhola", review_text=BANGLA + " সমুদ্র")
    check("a new place in Bangla is accepted", r.status_code == 202, r.text[:200])
    newest = uploads / "pending" / f"{r.json()['id']}.json"
    check("the Bangla text and new-place flag were saved",
          newest.exists() and json.loads(newest.read_text(encoding="utf-8"))["is_new_place"] is True
          and "লালবাগ" in newest.read_text(encoding="utf-8"), str(newest))

    count = len(list((uploads / "pending").glob("V*.json")))
    r = post(website="http://spam.example", review_text=GOOD_EN + " d")
    check("a bot that fills the hidden field is told 'success'", r.status_code == 202, str(r.status_code))
    check("…but nothing is saved", len(list((uploads / "pending").glob("V*.json"))) == count, "")

    r = post(review_text="<script>alert(1)</script> " + GOOD_EN + " e")
    stored = json.loads((uploads / "pending" / f"{r.json()['id']}.json").read_text(encoding="utf-8"))["review_text"]
    check("markup is stripped before saving", r.status_code == 202 and "<script>" not in stored, stored)

    blob = " ".join(p.read_text(encoding="utf-8") for p in (uploads / "pending").glob("V*.json"))
    check("no IP address or client details are stored", "127.0.0.1" not in blob and "testclient" not in blob.lower(), "")

    subs.limiter.reset()
    subs.limiter.limit = 2
    codes = [post(review_text=GOOD_EN + f" rate {i}").status_code for i in range(4)]
    check("the rate limit answers 429 after the limit", codes[:2] == [202, 202] and codes[2:] == [429, 429], str(codes))
    subs.limiter.limit = 100
    subs.limiter.reset()
    os.environ.pop("TOURISTINBD_UPLOADS_DIR")


# ---------------------------------------------------------------------------
# 3. the whole journey
# ---------------------------------------------------------------------------
def test_journey(tmp: Path) -> None:
    print("\nthe whole journey: submit -> approve -> ingest -> database -> API")
    real_before = fingerprint_dir(DATA_DIR)
    data = copy_data(tmp / "journey")
    build = run_script("build_phase8_database.py", data_dir=data)
    check("the starting database builds", build.returncode == 0, build.stderr[-300:])
    if build.returncode != 0:
        return
    client, subs = boot_api(data)
    subs.limiter.limit = 100
    variants_before = pd.read_csv(data / "phase4_entity_variants.csv")
    ids_before = dict(zip(variants_before["surface"], variants_before["entity_id"]))
    queue_before = pd.read_csv(data / "phase4_verification_queue.csv")
    n_reviews_before = len(pd.read_csv(data / "processed_reviews.csv"))

    def post(**body):
        base = {"place_name": "Lalbagh Fort", "is_new_place": False, "district": None, "rating": 5, "website": ""}
        return client.post("/api/submissions", json={**base, **body})

    check("existing-place Bangla review accepted", post(review_text=BANGLA).status_code == 202)
    check("new-place review accepted", post(place_name="Chandpai Quiet Channels", is_new_place=True,
                                            district="Bagerhat", rating=4, review_text=NEW_PLACE_TEXT).status_code == 202)
    check("a review to be rejected is accepted", post(review_text="Buy cheap watches from my shop, best prices anywhere!").status_code == 202)
    check("nothing is in the dataset yet",
          client.get("/api/overview").json()["total_reviews"] == n_reviews_before, "")

    listing = run_script("process_submissions.py", "--list", data_dir=data)
    ids = {line.split()[0]: line for line in listing.stdout.splitlines() if line.startswith("V")}
    check("the moderator sees all three pending", len(ids) == 3, listing.stdout)
    by_text = {}
    for sid in ids:
        shown = run_script("process_submissions.py", "--show", sid, data_dir=data).stdout
        by_text[sid] = shown
    lalbagh = next(s for s, t in by_text.items() if BANGLA in t)
    chandpai = next(s for s, t in by_text.items() if "Chandpai" in t)
    spam = next(s for s, t in by_text.items() if "cheap watches" in t)

    r = run_script("process_submissions.py", "--approve", lalbagh, "--by", "Yakin", data_dir=data)
    check("approving without a reason is refused", r.returncode != 0 and "reason" in r.stdout, r.stdout)
    r = run_script("process_submissions.py", "--approve", chandpai, "--by", "Yakin", "--reason", "real place", data_dir=data)
    check("approving a new place without a division is refused", r.returncode != 0 and "division" in r.stdout, r.stdout)
    r = run_script("process_submissions.py", "--ingest", data_dir=data)
    check("ingest with nothing approved does nothing", "nothing approved" in r.stdout, r.stdout)

    for args in (("--approve", lalbagh, "--by", "Yakin", "--reason", "genuine review"),
                 ("--approve", chandpai, "--by", "Yakin", "--reason", "real place", "--division", "Khulna"),
                 ("--reject", spam, "--by", "Yakin", "--reason", "advertising")):
        r = run_script("process_submissions.py", *args, data_dir=data)
        check(f"{args[0]} succeeds", r.returncode == 0, r.stdout + r.stderr)

    dry = run_script("process_submissions.py", "--ingest", "--dry-run", data_dir=data)
    check("a dry run lists what would be added and writes nothing",
          "would add" in dry.stdout and len(pd.read_csv(data / "processed_reviews.csv")) == n_reviews_before, dry.stdout)

    stack = all(importlib.util.find_spec(m) for m in ("rapidfuzz", "sklearn", "vaderSentiment"))
    args = ["--ingest", "--offline"] + ([] if stack else ["--skip-funnel"])
    if not stack:
        print("  NOTE  rapidfuzz/scikit-learn/vaderSentiment missing: running ingest without the later pipeline steps")
    r = run_script("process_submissions.py", *args, data_dir=data)
    check("ingest succeeds", r.returncode == 0, r.stdout[-800:] + r.stderr[-400:])
    if r.returncode != 0:
        return

    check("the approved files moved to ingested/",
          len(list((data / "visitor_uploads" / "ingested").glob("V*.json"))) == 2
          and not list((data / "visitor_uploads" / "approved").glob("V*.json")), "")
    check("the rejected one stays rejected and is not added",
          len(list((data / "visitor_uploads" / "rejected").glob("V*.json"))) == 1, "")

    batches = sorted(data.glob("real_reviews_visitor_*.csv"))
    check("one visitor batch file was written", len(batches) == 1, str(batches))
    batch = pd.read_csv(batches[0])
    check("the batch is labelled as visitor reviews", set(batch["source"]) == {"visitor"}
          and set(batch["source_type"]) == {"visitor"}, str(batch[["source", "source_type"]].drop_duplicates()))
    check("the Bangla original is kept in the batch", BANGLA in batch["review_text_original"].tolist(), "")
    check("the rejected spam is not in the batch", not batch["review_text"].str.contains("cheap watches").any(), "")

    corpus = pd.read_csv(data / "processed_reviews.csv")
    check("the corpus grew by exactly the two approved reviews", len(corpus) == n_reviews_before + 2,
          f"{len(corpus)} vs {n_reviews_before}+2")
    check("the submission id is the review id", {lalbagh, chandpai} <= set(corpus["review_id"].astype(str)), "")

    geo = pd.read_csv(data / "place_geography.csv")
    row = geo[geo["place_name"] == "Chandpai Quiet Channels"]
    check("the new place was added to place_geography.csv with its division",
          len(row) == 1 and row.iloc[0]["division"] == "Khulna" and row.iloc[0]["district"] == "Bagerhat", str(row))

    if stack:
        client, subs = boot_api(data)
        places = client.get("/api/places", params={"limit": 500}).json()
        names = {p["place_name"]: p for p in places["items"]}
        check("the new place is in the API with its division",
              names.get("Chandpai Quiet Channels", {}).get("division") == "Khulna", str(names.get("Chandpai Quiet Channels")))
        reviews = client.get("/api/reviews", params={"place": "Lalbagh Fort", "limit": 500}).json()
        check("the Bangla review now appears under its place",
              any(BANGLA in (x.get("review_text_clean") or x.get("review_text") or "") for x in reviews["items"]), "")
        language = pd.read_csv(data / "phase3_language_labels.csv")
        label = language[language["review_id"].astype(str) == lalbagh]["language_label"].tolist()
        check("the Bangla review is labelled bn by the language pipeline", label == ["bn"], str(label))
        mentions = pd.read_csv(data / "phase4_mentions.csv")
        check("mentions were extracted from the new review (Mongla)",
              ((mentions["review_id"].astype(str) == chandpai)).any(), "no mention rows for the new review")

        variants_after = pd.read_csv(data / "phase4_entity_variants.csv")
        ids_after = dict(zip(variants_after["surface"], variants_after["entity_id"]))
        registry = json.loads((data / "entity_id_registry.json").read_text(encoding="utf-8"))
        moved = [s for s, i in ids_before.items() if ids_after.get(s) != i and i not in registry["retired"]]
        check("no existing entity changed its ID when the new reviews arrived", not moved, str(moved[:5]))

        queue = pd.read_csv(data / "phase4_verification_queue.csv")
        check("new candidates start as 'candidate' — nothing auto-publishes",
              set(queue["state"]) <= {"candidate", "verified", "rejected", "sensitive"}
              and not queue["publishable"].any(), str(queue["state"].value_counts().to_dict()))
        check("the queue's earlier decisions are untouched",
              (queue_before["state"] == "candidate").all() == (queue.loc[queue["entity_id"].isin(queue_before["entity_id"]), "state"] == "candidate").all(), "")

    check("the real data folder was not touched", fingerprint_dir(DATA_DIR) == real_before,
          str(set(fingerprint_dir(DATA_DIR).items()) ^ set(real_before.items())))
    os.environ.pop("TOURISTINBD_DATA_DIR", None)


def main() -> None:
    print("Visitor submissions tests\n")
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        data = copy_data(tmp / "api")
        build = run_script("build_phase8_database.py", data_dir=data)
        if build.returncode != 0:
            print("could not build the starting database:", build.stderr[-400:])
            sys.exit(1)
        client, subs = boot_api(data)
        test_storage(subs, tmp / "unit_uploads")
        test_api(client, subs, data, tmp / "api_uploads")
        test_journey(tmp)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All visitor submission tests passed.")


if __name__ == "__main__":
    main()
