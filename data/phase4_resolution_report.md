# Phase 4 — Entity resolution

Clusters mentions of the same real thing (BUILD_PLAN 5.3). Unresolved
spelling variants split one place's evidence, and section 5.5 needs 2-3
independent mentions before anything becomes a candidate — so this step is
what stops variants suppressing the gems the project is looking for.

- Distinct surface forms in: **821**
- Entities out: **527**
- Entities with more than one variant: **117**
  - of which substantive (not just letter case): **100**
  - case-only: 17

Weights (fixed in advance): {'phonetic': 0.4, 'string': 0.25, 'containment': 0.2, 'geography': 0.15}, merge threshold 0.72.

Surfaces carrying 0 mentions are the corpus's own place names, added so a
short form found in someone else's review has an official name to resolve
against. A place having reviews is not the same as its name being mentioned,
so they contribute no mentions to the evidence counts.

## Substantive variant groups

Spelling and local-vs-official cases — what section 5.3 is actually about.

| entity | variants | mentions |
| --- | --- | --- |
| Bandarban | Bandarban, bandarban, বান্দরবন, বান্দরবান, বান্দারবান | 664 |
| Cox's Bazar | Cox'S Bazar, Cox's Bazar, Cox's Bazar Beach, Cox's Bazar beach, Cox's bazar, cox's Bazar, cox's bazar, কক্সবাজার | 593 |
| Picnic | PICNIC, Picnic, picnic, পিকনিক | 514 |
| Trekking and hiking | Hike, Hiking, Trek, Trekking, hike, hiking, trek, trekking, ট্রেকিং, হাইকিং | 459 |
| Boat ride | Boat Ride, Boat ride, Boat trip, Boating, boat Ride, boat ride, boat trip, boating, নৌকা ভ্রমণ, নৌকা ভ্রমন, নৌকাভ্রমণ | 404 |
| Padma | Padma, Padma Garden Footbridge, padma, পদ্মা | 322 |
| CNG auto-rickshaw | CNG, cng, সিএনজি | 294 |
| Guava | Guava, guava, পেয়ারা, পেয়ারা মাখা | 249 |
| Sitakunda | Sitakunda, sitakunda, শীতাকুণ্ড, শীতাকুন্ড, সিতাকুন্ড, সীতাকুণ্ড, সীতাকুন্ড | 238 |
| Bagerhat | Bagerhat, বাগেরহাট | 219 |
| Sreemangal | Sreemangal, Srimangal, Srimangal Tea Garden, sreemangal, srimangal, শ্রীমঙ্গল | 177 |
| Swimming | Swimming, swimming, সাঁতার | 166 |
| Rangamati | Rangamati, rangamati, রাঙামাটি, রাঙ্গামটি, রাঙ্গামাটি, রাঙ্ামাটি | 159 |
| Khagrachari | Khagrachari, Khagrachari HDCH Park, khagrachari, খগড়াছড়ি, খাগরাছড়ি, খাগড়াছড়ি | 155 |
| Sundarbans | Sundarbans, sundarbans, সুন্দরবন | 116 |
| Mahasthangarh | Mahasthangarh, mahasthangarh, মহাস্তানগড়, মহাস্থানগড়, মাহাস্থানগড় | 111 |
| Kayaking | Kayak, Kayaking, kayak, kayaking, কায়াক, কায়াকিং | 110 |
| Seafood | Sea Food, Sea food, Seafood, sea food, seafood, seafood shack, সামুদ্রিক মাছ | 106 |
| Lalakhal | Lalakhal, lalakhal, লালাখাল | 101 |
| Durgapur | Durgapur, durgapur, দুর্গাপুর, দূর্গাপুর | 88 |
| Engine boat (trawler) | Engine boat, engine boat, trawler, ইঞ্জিন নৌকা, ট্রলার | 86 |
| Mongla | Mongla, mongla, মংলা, মোংলা | 79 |
| Speedboat ride | Speed Boat, Speedboat, speed boat, speedboat, স্পিড বোট, স্পিডবোট | 78 |
| Bichnakandi Tourist Spot | Bichnakandi Tourist Spot, Bisnakandi, bisnakandi, বিসনাকান্দি | 67 |
| Jaflong | Jaflong, Jaflong Zero Point, jaflong, জাফলং | 63 |
| Shopping | Shopping, shopping, কেনাকাটা | 60 |
| Camping | Camping, camping, ক্যাম্পিং, তাঁবু | 59 |
| Sunset watching | Watching the sunset, watch the sunset, watching the sunset, সূর্যাস্ত দেখা | 50 |
| Birisiri | Birisiri, বিরিশরির, বিরিশিরি, বিরিসিরি, বিড়িসিড়ি | 48 |
| Fuchka | Fuchka, fuchka, phuchka, ফুচকা | 45 |
| Green coconut (dab) | Fresh coconut, coconut water, fresh coconut, green coconut, ডাব | 42 |
| Launch | launch ghat, লঞ্চ | 41 |
| Horse riding | Horse ride, Horse riding, horse ride, horse riding | 39 |
| Chander gari (jeep) | Chander Gari, Chander gari, chander gari, jeep ride, চাঁদের গাড়ি | 37 |
| Barbecue | BBQ, Barbecue, barbecue, bbq, বারবিকিউ | 33 |
| Best Time to Visit | Best Time to Visit, Best Time to Visit The best time to visit, Best time to visit, best time to visit | 32 |
| Bird watching | Birdwatching, bird watching, birdwatching, পাখি দেখা | 32 |
| Mango | Mango, mango, আমের | 32 |
| Tea stalls | Tea stall, tea stall, টং | 32 |
| Saint Martin | Saint Martin, Saint martin, সেন্ট মার্টিন | 32 |
| Chotpoti | Chotpoti, chotpoti, চটপটি | 30 |
| Muradpur | Muradpur, muradpur, মুরাদপুর | 28 |
| Sardar Bari | Sardar Bari, Sardar bari, sardar bari, সরদার বাড়ি, সর্দার বাড়ি | 27 |
| Paharpur | Paharpur, পাহাড়পুর | 25 |
| Kantajew Temple | Kantajew Temple, Kantajew temple, Kantaji Temple | 24 |
| Fried fish | Fish Fry, fish fry, fried fish, ভাজা মাছ, মাছ ভাজা | 23 |
| Dried fish (shutki) | Shutki, dried fish, shutki, শুঁটকি, শুটকি | 23 |
| Jackfruit | jackfruit, কাঁঠাল | 20 |
| Kaptai | Kaptai, Kaptai Lake, Kaptai lake, কাপ্তাই, কাপ্তাই লেক, কাপ্তায় | 20 |
| Gangamati | Gangamati, গঙ্গামতি, গঙ্গামাটি | 20 |
| Alutila | AluTila Cave, Alutila, Alutila Cave, Alutila cave, আলুটিলা | 19 |
| Kuakata | Kuakata, Kuakata Sea Beach, Kuakata sea beach, কুয়াকাটা | 19 |
| Cycling | bicycle, cycling | 17 |
| Shashi Lodge | Shashi Lodge, Shoshi Lodge, শশী লজ | 16 |
| Bamboo chicken | Bamboo Chicken, Bamboo chicken, bamboo chicken, বাঁশ মুরগি, ব্যাম্বু চিকেন | 14 |
| Parasailing | Parasailing, parasailing, প্যারাসেইলিং | 14 |
| Shrimp | prawn, shrimp, চিংড়ি | 14 |
| Biryani | Biriyani, biriyani, biryani, kacchi, বিরিয়ানি | 13 |
| Kolatoli Beach | Kolatoli Beach, kolatoli beach, কলাতলি বিচ, কলাতলি বীচ, কলাতলী বিচ, কলাতলী বীচেও | 13 |
| Nilgiri | Nilgiri, nilgiri, নীলগিরি | 13 |
| Lobster | Lobster, lobster, লবস্টার | 12 |
| Ahsan Manzil | Ahsan Manzil, Ahsan Manzil Museum, আহসান মঞ্জিল | 12 |
| Jhal muri | Jhalmuri, jhal muri, jhalmuri, ঝালমুড়ি | 11 |
| Ratargul | Ratargul Swamp Forest, ratargul, রাতারগুল | 11 |
| Kulfi | Kulfi, Kulphi, কুলফি | 10 |
| Bamboo raft ride | bamboo raft, raft ride, বাঁশের ভেলা | 10 |
| Hilsa (ilish) | hilsa, ইলিশ | 10 |
| Crab fry | Crab Fry, Crab fry, crab fry, কাঁকড়া ফ্রাই, কাঁকড়া ভাজা | 9 |
| Guliakhali Sea Beach | Guliakhali Sea Beach, Guliyakhali, guliyakhali, গুলিয়াখালি সি বিচ | 9 |
| Cable car | cable car, ক্যাবল কার | 9 |
| Pineapple | pineapple, আনারস | 9 |
| China Matir Pahar | China Matir Pahar, China Matir pahar, চিনা মাটির পাহাড়, চীনা মাটির পাহাড় | 9 |
| Jet ski | jet ski, জেট স্কি | 8 |
| Chandranath | Chandranath, Chandranath Hill, চন্দ্রনাথ | 8 |
| Roasted corn | corn, ভুট্টা | 7 |
| Papaya | Papaya, papaya, পেঁপে | 6 |
| Kotka | Kotka, Kotka Sea Beach, কটকা, কোটকা | 6 |
| Rupchanda (pomfret) | Rupchanda, রূপচাঁদা | 6 |
| Date palm juice | Khejurer Rosh, date palm juice, খেজুরের রস | 5 |
| Kotkoti (Mahasthan sweet) | kotkoti, কটকটি | 5 |
| Madhabpur Lake | Madhabpur Lake, madhabpur lake, মাধবপুর লেক | 5 |
| Kabab | Kabab, kabab, kebab, কাবাব | 4 |
| Sugarcane juice | sugarcane juice, আখের রস | 4 |
| Boga Lake | Boga Lake, বগা লেক | 4 |
| Mohamaya Lake | Mohamaya Lake, mohamaya lake, মহামায়া লেক | 4 |
| Sada Matir Pahar | SADA MATIR PAHAR, Sada Matir Pahar (White Clay Hills), সাদা মাটির পাহাড় | 4 |
| Khichuri | Khichuri, খিচুড়ি | 3 |
| best time to visit is during the rainy season | best time to visit is during rainy season, best time to visit is during the rainy season | 3 |
| go early in the morning to | Go Early in the Morning, go early in the morning to | 3 |
| Seven-layer tea | Seven Layer Tea, seven-layer tea | 3 |
| Karamjal | Karamjal, করমজল | 3 |
| Tanguar Haor | Tanguar Haor, টাংগুয়ার হাওর, টাংগুয়ার হাওড় | 3 |
| Nilachal | Nilachal, Nilachal Tourist Center, নীলাচল | 3 |
| Fatrar Chor | Fatrar Chor, ফাতরার চর | 3 |
| Doi (curd) | দই, মহিষের দুধের দই | 3 |
| Lawachara National Park | Lawachara, Lawachara National Park | 2 |
| Paan | Rongila Pan, paan | 2 |
| Bijoypur Lake | Bijoypur Lake, বিজয়পুর লেক | 2 |
| Madhabkunda | Madhabkunda Waterfall, মাধবকুণ্ড | 2 |
| Foy's lake | Foy's Lake, Foy's Lake Resort, Foy's lake | 1 |

## Case-only groups

Trivially easy; listed separately so they are not read as evidence that
resolution works.

- Hiron Point, Hiron point, hiron point
- Honey, honey
- I-Badh, i-badh
- Kachagolla, kachagolla
- Panam City, Panam city, panam city
- Pashur, pashur
- PUTHIA, Puthia
- Ramna Park, Ramna park
- Sajek Valley, Sajek valley, sajek valley
- Street Food, Street food, street Food, street food
- T-Badh, T-badh, t-badh
- Take a CNG or Auto, take a CNG or auto
- Visit early in the morning or, visit early in the morning or
- Carry water, carry water
- Go early, go early
- Patenga Sea Beach, patenga sea beach
- Varendra Research Museum, varendra research museum

## Evaluation against the hand-made variant groups

- Gold surfaces: 35 (29 present in the corpus)
- B-cubed precision: 0.9655
- B-cubed recall: 0.9655
- **B-cubed F1: 0.9655**
- Cluster purity: 0.9655

Gold surfaces the corpus does not contain, so they could not be scored:

- `Char Bijoy`
- `Guliakhali`
- `Gulyakhali`
- `Kuakata Beach`
- `Ratargul`
- `kaptai`

## Notes

- embedding signal unavailable (needs torch); phonetic + string + geography only
