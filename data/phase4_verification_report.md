# Phase 4 — Verification queue

Nothing auto-publishes (BUILD_PLAN 5.7). A high gem score decides what a
district officer sees first; only a recorded human decision makes anything
visible to the public.

- Candidates in the queue: **76**
- Publishable to the tourist side: **0**
- In the district register (everything but rejected): **76**

## States

| state | meaning | count | tourist-visible |
| --- | --- | --- | --- |
| candidate | extracted and resolved, awaiting a human decision | 76 | no |
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
| Best Time to Visit | 0.95 | unknown | 31 | Barishal|Chattogram|Dhaka|Rajshahi|Sylhet |
| Bisnakandi | 0.85 | V0 | 28 | Sylhet |
| Kantaji Temple | 0.85 | V0 | 16 | Rajshahi|Rangpur |
| Sardar Bari | 0.80 | V1 | 14 | Dhaka |
| Gangamati | 0.79 | V0 | 6 | Barishal |
| Nilgiri | 0.76 | V1 | 9 | Chattogram |
| Pashur | 0.75 | V1 | 10 | Chattogram|Khulna |
| visit early in the morning or | 0.74 | unknown | 5 | Chattogram|Dhaka|Sylhet |
| Guliyakhali | 0.73 | V0 | 6 | Chattogram |
| China Matir Pahar | 0.71 | V0 | 5 | Mymensingh |
| T-badh | 0.69 | V0 | 4 | Rajshahi |
| Jaflong | 0.67 | V2 | 21 | Mymensingh|Sylhet |
| Panam City | 0.67 | V1 | 8 | Dhaka |
| Mongla | 0.67 | V2 | 30 | Khulna |
| Sitakunda | 0.66 | V2 | 56 | Chattogram|Sylhet |
| best time to visit is during the winter months | 0.66 | unknown | 3 | Dhaka |
| Mahasthangarh | 0.66 | V2 | 36 | Rajshahi |
| Lalakhal | 0.65 | V2 | 19 | Sylhet |
| Kolatoli Beach | 0.65 | V1 | 5 | Chattogram |
| Boga Lake | 0.65 | V1 | 3 | Chattogram |

