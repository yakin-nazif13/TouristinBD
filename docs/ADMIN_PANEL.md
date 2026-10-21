# Admin panel (for the website's owners)

A private page where the owners read the reviews visitors have sent, approve or reject them, and
add the approved ones to the dataset. There is a small "Owner login" link in the public site's footer,
but visitors cannot do anything on the page without an owner's email **and** the shared password.

```
Visitor sends a review  ->  waits in  data/visitor_uploads/pending/
Owner signs in at /admin  ->  Approve or Reject (with a reason)
Owner presses "Add to dataset"  ->  the pipeline runs and the reviews appear on the site
```

## How logging in works
- The owners share **one password**.
- Each owner signs in with **their own email address** plus that password.
- Only emails on the owners' list can sign in, so knowing the password is not enough.
- The owner's email is shown on every approval or rejection, to all owners.

## Setting it up (already done for the first owner)
The panel is switched off until a password is set **and** at least one owner email is added.
On the machine that runs the site:

```bash
.venv/bin/python scripts/manage_admins.py set-password                  # the shared password (hidden prompt)
.venv/bin/python scripts/manage_admins.py add-owner someone@example.com # let this email sign in
.venv/bin/python scripts/manage_admins.py list
.venv/bin/python scripts/manage_admins.py remove-owner someone@example.com   # also signs them out
```

No restart is needed. The password is typed at a hidden prompt, never on the command line, must be at
least 10 characters, and is stored only as a salted hash in `data/admin_users.json`.
**Never commit that file** (git ignores it). Changing the password signs everyone out.

## Using it

1. Open **`/admin`** (for example http://127.0.0.1:8000/admin, or the "Owner login" link in the site footer) and sign in with your email and the shared password.
2. The buttons at the top show how many reviews are *Pending*, *Approved*, *Rejected* and
   *Added to dataset*. Click one to see that list.
3. Each card shows the place, stars, when it was sent and the full text (Bangla is fine).
   - **Approve**: type a reason. If it is a *new place*, also choose its **division** (and check the
     district and town). The division is needed so the itinerary planner and district register can
     place it.
   - **Reject**: type a reason.
   - You can change your mind about an approved or rejected review until it has been added to the
     dataset. Both decisions stay on record.
4. When you have approved what you want, press **Add N approved reviews to the dataset**. It runs
   these steps and shows each one as it goes: add -> clean -> language label -> mentions -> merge
   spellings -> check maps -> gem score -> verification queue -> rebuild database. It takes a few
   minutes.
   - *Skip the live map lookups* works without internet (new names are then "unknown", never "hidden").
   - *Only add and clean* skips the later steps.
5. If a step fails, the approved reviews stay where they are. Fix the cause and press the button again.
6. Sign out when you finish. Sessions also end after 8 hours, or when the server restarts.

Your email on every decision comes from your login. It cannot be typed in or changed on the page.

## Safeguards

| Risk | Protection |
|---|---|
| A visitor approves their own review | every admin route needs a signed-in owner (a registered email **and** the password); the tests check **every** route in the API's schema returns 401 without one |
| Guessing the password | 5 wrong tries on an email (or 10 from one computer) locks sign-in for 15 minutes |
| Stolen accounts file | the password is stored as a salted scrypt hash; the file is readable by its owner only |
| Finding out which emails are owners | a wrong password and an unregistered email give the same answer and take the same time |
| Another website acting as the owner | no cookies are used; the page sends a token in a header |
| Hostile text inside a review | the page shows review text as plain text only, never as HTML |
| Private text kept by browsers | admin responses are sent with `Cache-Control: no-store` |
| Two ingests at once | one at a time (also across the command line and the panel) |
| Sloppy audit trail | a reason and the owner's email are recorded for every decision |

## Settings

| Environment variable | Meaning | Default |
|---|---|---|
| `TOURISTINBD_ADMIN_USERS_FILE` | where the owner accounts are stored | `data/admin_users.json` |
| `TOURISTINBD_UPLOADS_DIR` | where visitor reviews are stored | `data/visitor_uploads` |

## Before a public launch
- **Use HTTPS.** Over plain `http://` a password and token can be read in transit. Local use is fine;
  Render and similar hosts give HTTPS automatically.
- **Saved disk.** The free Render plan erases files on every restart, so `admin_users.json` and the
  pending reviews would disappear. Put `TOURISTINBD_ADMIN_USERS_FILE` and `TOURISTINBD_UPLOADS_DIR`
  on a persistent disk, or move them into a database.
- **"Add to dataset" needs the research packages** (`rapidfuzz`, `scikit-learn`, `vaderSentiment`,
  `langdetect`) and the pipeline scripts. The slim public image does not include them, so the panel
  says so instead of half-running. Either build a fuller image, or approve on the public site and run
  `python scripts/process_submissions.py --ingest` on your own computer.
- **A shared password is a weaker design.** The email is a label, not proof: anyone who knows the
  password and an owner's email can act as that owner, so the "who approved it" record is only as
  trustworthy as the password's secrecy. Keep it private, change it when someone leaves
  (`set-password`), and choose a longer, less guessable one than a short pattern before a public launch.
  Per-owner passwords would remove the weakness.
- Sign-in lock-outs are in memory and reset on restart. A determined attacker can also lock an owner's
  name for 15 minutes by failing on purpose; that is a nuisance, not a break-in.
- Roles (for example, district officers who may only verify their own district) are future work
  (`docs/BUILD_PLAN.txt`, section 7.3). Every owner can currently do everything the panel offers.

## Tests
`scripts/test_admin.py` (117 checks): the shared password and owner emails (including "the right password
with an unregistered email is refused"), sessions, lock-out, every admin route refusing a
visitor, the approver coming from the login, the full background ingest on a throwaway copy of the
data (including a second run being refused), and the page itself (no stored credentials, no HTML built
from visitor text, every route and element it uses exists).
