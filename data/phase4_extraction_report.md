# Phase 4 — Entity extraction

Extractor: **gazetteer**. Section 5.2's grounding rule is applied to every
candidate: a surface form that cannot be located in the review is dropped.

- Reviews processed: **14841**
- Grounded mentions: **7509**
- Reviews with at least one: 3597
- Distinct surface forms: 725

## Grounding

- Candidates proposed: 7509
- Kept: 7509
- Dropped: 0 (**0.0%**)

| match kind | mentions |
| --- | --- |
| exact | 7509 |

## By entity type

| type | mentions |
| --- | --- |
| ACCESS | 562 |
| ACTIVITY | 2040 |
| FOOD | 919 |
| PLACE | 3698 |
| TIP | 290 |

## Most-mentioned surfaces

| surface | mentions |
| --- | --- |
| Bandarban | 383 |
| picnic | 348 |
| কক্সবাজার | 311 |
| Cox's Bazar | 238 |
| boat ride | 218 |
| বান্দরবান | 217 |
| Padma | 183 |
| পিকনিক | 145 |
| সিএনজি | 141 |
| CNG | 131 |
| পদ্মা | 128 |
| সীতাকুণ্ড | 126 |
| বাগেরহাট | 122 |
| পেয়ারা | 120 |
| trekking | 119 |
| swimming | 117 |
| hiking | 101 |
| Bagerhat | 97 |
| guava | 96 |
| Sonargaon | 92 |

## Mentions written in Bangla script

- **2749** mention(s) in 1136 review(s), from the reviewed spellings in `place_names_bn.csv` and `food_activity_lexicon.csv`

## Foods, activities and transport

Every spelling below was found in real review text before it was added
(`food_activity_lexicon.csv`, which also records each rejected spelling and why).

| type | concept | reviews | mentions | spellings found |
| --- | --- | --- | --- | --- |
| FOOD | Seafood | 101 | 106 | sea food, seafood, seafood shack, সামুদ্রিক মাছ |
| FOOD | Guava | 94 | 249 | guava, পেয়ারা, পেয়ারা মাখা |
| FOOD | Street food | 66 | 70 | street food |
| FOOD | Fuchka | 42 | 45 | fuchka, phuchka, ফুচকা |
| FOOD | Barbecue | 31 | 33 | barbecue, bbq, বারবিকিউ |
| FOOD | Tea stalls | 31 | 32 | tea stall, টং |
| FOOD | Green coconut (dab) | 30 | 42 | coconut water, fresh coconut, green coconut, ডাব |
| FOOD | Mango | 29 | 32 | mango, আমের |
| FOOD | Chotpoti | 28 | 30 | chotpoti, চটপটি |
| FOOD | Fried fish | 22 | 23 | fish fry, fried fish, ভাজা মাছ, মাছ ভাজা |
| FOOD | Dried fish (shutki) | 17 | 23 | dried fish, shutki, শুঁটকি, শুটকি |
| FOOD | Jackfruit | 16 | 20 | jackfruit, কাঁঠাল |
| FOOD | Banana | 14 | 15 | banana |
| FOOD | Shrimp | 14 | 14 | prawn, shrimp, চিংড়ি |
| FOOD | Bamboo chicken | 13 | 14 | bamboo chicken, বাঁশ মুরগি, ব্যাম্বু চিকেন |
| FOOD | Coffee | 12 | 14 | কফি |
| FOOD | Biryani | 11 | 13 | biriyani, biryani, kacchi, বিরিয়ানি |
| FOOD | Jhal muri | 11 | 11 | jhal muri, jhalmuri, ঝালমুড়ি |
| FOOD | Lobster | 11 | 12 | lobster, লবস্টার |
| FOOD | Pickle | 11 | 11 | pickle |
| FOOD | Kulfi | 10 | 10 | kulfi, kulphi, কুলফি |
| FOOD | Crab fry | 9 | 9 | crab fry, কাঁকড়া ফ্রাই, কাঁকড়া ভাজা |
| FOOD | Pineapple | 9 | 9 | pineapple, আনারস |
| FOOD | Hilsa (ilish) | 6 | 10 | hilsa, ইলিশ |
| FOOD | Papaya | 6 | 6 | papaya, পেঁপে |
| FOOD | Roasted corn | 5 | 7 | corn, ভুট্টা |
| FOOD | Bhorta | 4 | 4 | ভর্তা |
| FOOD | Date palm juice | 4 | 5 | date palm juice, khejurer rosh, খেজুরের রস |
| FOOD | Kabab | 4 | 4 | kabab, kebab, কাবাব |
| FOOD | Kotkoti (Mahasthan sweet) | 4 | 5 | kotkoti, কটকটি |
| FOOD | Rupchanda (pomfret) | 4 | 6 | rupchanda, রূপচাঁদা |
| FOOD | Sugarcane juice | 4 | 4 | sugarcane juice, আখের রস |
| FOOD | Doi (curd) | 3 | 3 | দই, মহিষের দুধের দই |
| FOOD | Khichuri | 3 | 3 | khichuri, খিচুড়ি |
| FOOD | Seven-layer tea | 3 | 3 | seven layer tea, seven-layer tea |
| FOOD | Duck curry | 2 | 2 | duck curry |
| FOOD | Ghol (buttermilk) | 2 | 3 | ঘোল |
| FOOD | Honey | 2 | 2 | honey |
| FOOD | Kachagolla | 2 | 4 | kachagolla |
| FOOD | Paan | 2 | 2 | paan, rongila pan |
| FOOD | Pitha | 2 | 2 | পিঠা |
| FOOD | Badam cha | 1 | 1 | badam cha |
| FOOD | Lemon sherbet | 1 | 2 | লেবুর শরবত |
| FOOD | Loitta fish | 1 | 1 | লইট্টা |
| FOOD | Mezbani | 1 | 1 | মেজবানি |
| FOOD | Rasmalai | 1 | 2 | রসমালাই |
| ACTIVITY | Picnic | 430 | 514 | picnic, পিকনিক |
| ACTIVITY | Boat ride | 353 | 404 | boat ride, boat trip, boating, নৌকা ভ্রমণ, নৌকা ভ্রমন, নৌকাভ্রমণ |
| ACTIVITY | Trekking and hiking | 309 | 459 | hike, hiking, trek, trekking, ট্রেকিং, হাইকিং |
| ACTIVITY | Swimming | 151 | 166 | swimming, সাঁতার |
| ACTIVITY | Kayaking | 82 | 110 | kayak, kayaking, কায়াক, কায়াকিং |
| ACTIVITY | Speedboat ride | 70 | 78 | speed boat, speedboat, স্পিড বোট, স্পিডবোট |
| ACTIVITY | Shopping | 57 | 60 | shopping, কেনাকাটা |
| ACTIVITY | Camping | 52 | 59 | camping, ক্যাম্পিং, তাঁবু |
| ACTIVITY | Sunset watching | 50 | 50 | watch the sunset, watching the sunset, সূর্যাস্ত দেখা |
| ACTIVITY | Horse riding | 38 | 39 | horse ride, horse riding |
| ACTIVITY | Bird watching | 28 | 32 | bird watching, birdwatching, পাখি দেখা |
| ACTIVITY | Cycling | 17 | 17 | bicycle, cycling |
| ACTIVITY | Parasailing | 14 | 14 | parasailing, প্যারাসেইলিং |
| ACTIVITY | River cruise | 10 | 11 | cruise |
| ACTIVITY | Bamboo raft ride | 9 | 10 | bamboo raft, raft ride, বাঁশের ভেলা |
| ACTIVITY | Cable car | 9 | 9 | cable car, ক্যাবল কার |
| ACTIVITY | Jet ski | 8 | 8 | jet ski, জেট স্কি |
| ACCESS | CNG auto-rickshaw | 223 | 294 | cng, সিএনজি |
| ACCESS | Engine boat (trawler) | 56 | 86 | engine boat, trawler, ইঞ্জিন নৌকা, ট্রলার |
| ACCESS | Chander gari (jeep) | 31 | 37 | chander gari, jeep ride, চাঁদের গাড়ি |
| ACCESS | Launch | 20 | 41 | launch ghat, লঞ্চ |

## Notes

- gazetteer of 178 known names (corpus + geography + 3.1 anchors)
- 153 reviewed Bangla spelling(s) of those names (place_names_bn.csv)
- 157 reviewed food / activity / transport spelling(s) (food_activity_lexicon.csv)
