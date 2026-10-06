# Phase 4 — Verification queue

Nothing auto-publishes (BUILD_PLAN 5.7). A high gem score decides what a
district officer sees first; only a recorded human decision makes anything
visible to the public.

- Candidates in the queue: **13**
- Publishable to the tourist side: **0**
- In the district register (everything but rejected): **13**

## States

| state | meaning | count | tourist-visible |
| --- | --- | --- | --- |
| candidate | extracted and resolved, awaiting a human decision | 13 | no |
| verified | a district officer confirmed it | 0 | yes |
| rejected | a district officer rejected it | 0 | no |
| sensitive | fragile ecology, restricted area or a private/home business | 0 | no |

`sensitive` is not a soft rejection. The item stays in the district register
with its evidence and never reaches the tourist side — fragile ecology,
permit areas such as parts of the Chittagong Hill Tracts, and private or
home businesses. Publishing one of those is the harm this queue exists to
prevent, and a crowd cannot be un-sent.

## Audit trail

Decisions are appended to `phase4_verification_log.csv`, never overwritten: who,
when, which state and why. An item's current state is its latest entry, and
a changed mind leaves both, because a register that rewrites its own history
cannot be audited.

## Awaiting a decision

| entity | score | visibility | reviews | divisions |
| --- | --- | --- | --- | --- |
| Gangamati | 0.69 | V0 | 2 | Barishal |
| Pashur | 0.62 | V1 | 4 | Khulna |
| Bandarban | 0.61 | V3 | 12 | Chattogram |
| Saint Martin | 0.61 | V3 | 14 | Chattogram |
| Sitakunda | 0.60 | V2 | 7 | Chattogram |
| Sonargaon | 0.60 | V3 | 13 | Dhaka |
| Mongla | 0.57 | V2 | 6 | Khulna |
| Muradpur | 0.51 | V2 | 4 | Chattogram |
| Cox's Bazar | 0.49 | V3 | 5 | Barishal|Chattogram |
| Bagerhat | 0.49 | V3 | 6 | Khulna |
| Rangamati | 0.43 | V3 | 5 | Chattogram |
| Sundarbans | 0.41 | V3 | 3 | Chattogram|Khulna|Sylhet |
| Sreemangal | 0.37 | V3 | 3 | Sylhet |

