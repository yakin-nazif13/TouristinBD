# Phase 4 — Verification queue

Nothing auto-publishes (BUILD_PLAN 5.7). A high gem score decides what a
district officer sees first; only a recorded human decision makes anything
visible to the public.

- Candidates in the queue: **54**
- Publishable to the tourist side: **0**
- In the district register (everything but rejected): **54**

## States

| state | meaning | count | tourist-visible |
| --- | --- | --- | --- |
| candidate | extracted and resolved, awaiting a human decision | 54 | no |
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
| Gangamati | 0.91 | V0 | 12 | Barishal|Khulna |
| Sardar Bari | 0.80 | V1 | 20 | Dhaka |
| Birisiri | 0.75 | V1 | 16 | Mymensingh |
| Pashur | 0.75 | V1 | 10 | Chattogram|Khulna |
| Fatrar Chor | 0.69 | V0 | 3 | Barishal |
| Nilgiri | 0.68 | V2 | 10 | Chattogram |
| Lalakhal | 0.68 | V2 | 38 | Sylhet |
| Mongla | 0.67 | V2 | 30 | Khulna |
| Sitakunda | 0.66 | V2 | 106 | Chattogram|Sylhet |
| Mahasthangarh | 0.65 | V2 | 36 | Rajshahi |
| Kaptai | 0.65 | V2 | 19 | Chattogram|Sylhet |
| Muradpur | 0.64 | V2 | 24 | Chattogram |
| Sada Matir Pahar | 0.63 | V1 | 4 | Mymensingh |
| Ahsan Manzil | 0.62 | V3 | 10 | Chattogram|Dhaka|Rangpur |
| Shashi Lodge | 0.61 | V1 | 4 | Mymensingh |
| Sundarbans | 0.60 | V3 | 33 | Barishal|Chattogram|Khulna|Mymensingh|Sylhet |
| Padma | 0.59 | V3 | 206 | Barishal|Chattogram|Khulna|Rajshahi|Sylhet |
| Kolatoli Beach | 0.59 | V3 | 11 | Chattogram |
| China Matir Pahar | 0.59 | V2 | 8 | Mymensingh |
| Sonargaon | 0.59 | V3 | 50 | Dhaka |

