# What translation loses

The same extractor run over the reviewer's own words and over Google's English
translation of the same review. The sample is every review Google Maps returned
in both versions, so nothing else differs.

- Bangla-script reviews compared: **285**
- Of the places, foods, activities and transport named in the original, the translation still names **69%** (95% interval 60%–77%, bootstrap over reviews)
- Even if every respelled name were recovered by fuzzy matching, at most **83%** would survive
- Places alone: **58 of 84** survive (69%)
- Banglish reviews: **10**; Google kept the meaning of **0 of 10** judged

| type | in original | in translation | kept | lost | only in translation | retention (95% CI) |
| --- | --- | --- | --- | --- | --- | --- |
| PLACE | 84 | 73 | 58 | 26 | 15 | 69% (59%–78%) |
| FOOD | 1 | 1 | 0 | 1 | 1 | 0% (0%–0%) |
| ACTIVITY | 9 | 10 | 7 | 2 | 3 | 78% (44%–100%) |
| ACCESS | 5 | 4 | 3 | 2 | 1 | 60% (20%–100%) |

## Which places each side misses

Places translation lost, against places our Bangla lists missed, by how well
known they already are (gazetteer visibility, V0 = on no map, V3 = famous).

| | little known (V0-V1) | known (V2-V3) | share little known |
| --- | --- | --- | --- |
| lost in translation | 9 | 13 | 41% |
| missing from our Bangla lists | 0 | 8 | 0% |

Fisher exact test, two-sided: p = 0.067. At this sample size the difference could be chance; it is a direction to test on more data, not a result.

## Lost in translation

`respelled`: the name is still there, spelled so the map cannot find it.
`translated_or_dropped`: the name was turned into a description, or left out.

| concept | outcome | original | translation |
| --- | --- | --- | --- |
| kotkoti (mahasthan sweet) | translated_or_dropped | …যাদি।। এখানকার জনপ্রিয় খাবার হচ্ছে কটকটি,, মহাস্থানের কটকটি সারাদেশে প… | Mahasthan is located in Shibganj Upazila of Bogra district. Everyone k… |
| kotka | respelled | কটকা সমুদ্র সৈকত থেকে সুন্দরবনের সৌন্দর্য ভালভাবে পর্যবেক্ষণ করা যায়।… | The beauty of the Sundarbans can be observed well from Katka beach. On… |
| launch | translated_or_dropped | …ি জন্য পানিতে নামা বেশ ঝুঁকিপূর্ণ। লঞ্চ হচ্ছে কটকাতে যাওয়ার প্রধান মাধ… | Katka is one of the most diverse places in the world's largest mangrov… |
| bird watching | translated_or_dropped | …সুন্দর চর, যেখানে বিভিন্ন প্রজাতির পাখি দেখা যায়। * লেবুর বন: সমুদ্রের… | Kuakata Sea Beach: A Wonderful Land of Nature Introduction: Kuakata is… |
| sunset watching | translated_or_dropped | …ণে সাধারণত সমুদ্রসৈকত, সূর্যোদয় ও সূর্যাস্ত দেখাই প্রধান আকর্ষণ হয়ে … | The mangrove forest of Kuakata is a beautiful and attractive travel de… |
| sada matir pahar | translated_or_dropped | নেত্রকোনার দুর্গাপুরে অবস্থিত সাদা মাটির পাহাড় প্রকৃতির এক অনন্য সৃষ্ট… | The white clay hills located in Durgapur, Netrakona are a unique creat… |
| birisiri | respelled | …পাহাড়," বাংলাদেশের নেত্রকোনা জেলার বিরিশিরি অঞ্চলে অবস্থিত একটি অত্যন্… | The White Clay Hills, or "Shada Matir Pahar," is a very beautiful natu… |
| sada matir pahar | respelled | সাদা মাটির পাহাড়, বা "শাদা মাটির পাহাড়," বাংলাদেশের নেত্রকোনা জেলার বি… | The White Clay Hills, or "Shada Matir Pahar," is a very beautiful natu… |
| bijoypur lake | respelled | …া মাটির পাহাড় একটি সুন্দর জায়গা। বিজয়পুর লেক এবং সিরামিক হিল-ই এখানে… | Vijaypur White Clay Hills is undoubtedly a beautiful place for nature … |
| china matir pahar | translated_or_dropped | … গিয়েছিলাম। এটি বাংলাদেশের একমাত্র চিনা মাটির পাহাড়। ভালোই লেগেছে। | I went for a walk. This is the only Chinese clay hill in Bangladesh. I… |
| bijoypur pahar | translated_or_dropped | বিজয়পুর পাহাড়ের সেরা ভিউ এইটি ♥ | This is the best view of Vijaypur hills ♥ |
| shreepur tea garden | respelled | শ্রীপুর টি গার্ডেনের এই পয়েন্ট বৃষ্টিকালিন সময়ে এক অপরূপ সৌন্দর্য ধারন… | This point in Sreepur Tea Garden has a unique beauty during the rainy … |
| finlay tea estate | respelled | …র্বোচ্চ চা উৎপাদনকারী প্রতিষ্ঠান " ফিনলে টি এস্টেট" । এদের প্রায় ১৭ টি… | The highest tea producing company in Bangladesh is "Finley Tea Estate"… |

## Found only in the translation — gaps in our own Bangla lists

These are not things translation added. The original names them in Bangla, and
our reviewed Bangla name list or food / activity list does not have that spelling
yet. Each is a candidate to add.

| concept | type | reviews |
| --- | --- | --- |
| ali amjad's clock | PLACE | 4 |
| khagrachari | PLACE | 4 |
| kuakata | PLACE | 3 |
| kuakata sea beach | PLACE | 2 |
| banana | FOOD | 1 |
| cng auto-rickshaw | ACCESS | 1 |
| cycling | ACTIVITY | 1 |
| mahasthan archaeological museum | PLACE | 1 |
| mahasthangarh | PLACE | 1 |
| speedboat ride | ACTIVITY | 1 |
| trekking and hiking | ACTIVITY | 1 |

## Banglish through Google Translate

Every pair, from `banglish_translation_check.csv`. The judgement column is a person's call
and can be changed there.

| reviewer wrote | Google's English | judgement |
| --- | --- | --- |
| Sondor jaiga | Sondor Jaiga | untranslated |
| Onek hatte hoy, but view onek sundor | One hatte hoy, but view one sundor | untranslated |
| Siri ar kase jawa tai ank kosto kor khara pahar | Siri is a good friend, but it is not enough to be a good friend. | meaning_lost |
| Ki ki diben ze ekhn ki | Who is the one who | meaning_lost |
| Ekhane giye akta fuchka kine kheyechilam, shei din ta valoi legechilo - onek batash chilo bikale. | I've been working hard for a long time, and I'm so happy that I've been able to do it - one day I'll be able to do it. | meaning_lost |
| sei gorom | six o'clock | meaning_lost |
| Ami tomakei sudo cai | I'm going to make you a sudo cai. | meaning_lost |
| Ei jaiga eto tai sundor je gele ar bari aste iccha korena | This place is full of beautiful flowers and the sun is shining brightly. | meaning_lost |
| Onek onek sundor | One piece one piece | meaning_lost |
| Eid er age giyacilam.. ak bar onek khn teka cilam basa tew bole jaini, onek khn cilam jaiga ta te onek kicuii dekhlam, Meya ra kmn kore jaccilo ki korcilo cela ra ki korcilo, oi khne celar ce meyai basi🙂 khali meya vai, diya onek dekha dekhir pore basaai cole asci😣 kintu kosto laglo sobai khali gf bf geca kew biya kore jaini oi khne🙂 Sobar ucit biya kore newa nahle pap hbe 🤓 | Eid is the age of giyacilam.. I have a bar where I can eat cilam and eat it, one of the cilams is a jaini, one of the cilams is a jaini, I don't know how to eat cilam, I don't know how to eat cilam🙂 I'm sorry, I'm sorry, I'm sorry😣 I'm sorry, | meaning_lost |

## Limits

- Our Bangla name list was mined from Bangla reviews, including some of these, so
  matching on the original has a home advantage for names already on it. The
  'only in translation' column is the opposite effect, so both are reported.
- Matching is by name, not meaning: a description like 'the white clay hills' is
  counted as lost even though a reader would recognise it.
- 285 reviews is a small sample, hence the intervals.
- Only Google Maps' own translation is measured, not other translators.
