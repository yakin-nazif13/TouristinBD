# Phase 8 — Database Build Report

- Built (UTC): 2026-10-21T12:20:48Z
- Database: `data/touristinbd.db` (schema version 2)

## Row counts

| table | rows |
| --- | --- |
| places | 27 |
| topics | 11 |
| reviews | 538 |
| preferences | 5 |
| topic_preference_map | 10 |
| long_tail_flags | 10 |
| validation_precision | 10 |
| validation_coverage | 5 |
| validation_recommendations | 4 |
| validation_manual_sample | 50 |
| sensitivity_metrics | 5 |
| sensitivity_mappings | 33 |
| review_language | 538 |
| entities | 162 |
| entity_variants | 167 |
| mentions | 183 |

## Views

- `v_city_preference_rollup`
- `v_city_stats`
- `v_dataset_overview`
- `v_entity_evidence`
- `v_language_mix`
- `v_mention_evidence`
- `v_place_stats`
- `v_preference_frequency`
- `v_rating_distribution`
- `v_review_preference`
- `v_temporal_volume`
- `v_venue_preference_rollup`

## Build notes

- place_geography.csv rows with no reviews yet (ignored): Adventure World Family Tourism Park, Ali Amjad's Clock, Alutila Cave, Baithakata Floating Market, Baliati Jamidar Bari, Bangladesh Folk Art & Crafts Foundation (Sonargaon), Bhawal National Park, Bhimruli Floating Guava Market, Bichnakandi Tourist Spot, Bijoypur Lake, Bijoypur Pahar (border hill), Boga Lake, Buddha Dhatu Jadi (Golden Temple), Chandranath Hill, China Matir Pahar, Choto Sona Masjid, Darianagar Nature & Tourism Center, Debotakhum, Dibir Haor Shapla Bil, Durga Sagar, Ethnological Museum, Finlay Tea Estate, Foy's Lake, Gulshan Society Lake Park, Guthia Baitul Aman Jame Mosque, Hatir Banglow, Hatirjheel Lake, Hazrat Shahjalal Mazar Sharif, Hillview Park & Cafe, Himchari Fountain and Hill, Hiron Point (Nilkamal), Hum Hum Waterfall, I-Badh, Jhau Bon Kuakata, Kantajew Temple, Khagrachari HDCH Park, Khoiyachara Waterfalls, Kolatoli Beach, Kotka Sea Beach, Laboni Point Sea Beach, Lala Khal Zero Point, Lawachara National Park, Madhabkunda Waterfall, Mahasthan Archaeological Museum, Mahasthangarh Tourism Park, Mangrove Forest Kuakata, Mayung Kopal (Stairs to Heaven), Michael Madhusudan Datta Memorial (Sagardari), Mini Bangladesh (Shadhinata Complex), Mohamaya Lake, Mujibnagar Monument Complex, Museum of Rajas' (Hason Raja Museum), Nafakhum Waterfall, National Botanical Garden, Natore Rajbari, Naval Sea Beach, New Zealand Para, Nijhum Dwip, Nilgiri, Noor Jahan Tea Garden, Osmani Museum, Padma Garden Footbridge, Patenga Sea Beach, Puthia Rajbari, Rajshahi Central Park & Zoo, Ramna Park, Ramsagar National Park, Risang Waterfall, Sada Matir Pahar (White Clay Hills), Saint Martin's Island West Beach, Sajek Valley, Shalban Bihar, Shashi Lodge, Shilaidaha Rabindra Kuthibari, Shopnopuri Artificial Amusement Park, Shreepur Tea Garden, Shuvolong Waterfalls, Sreepur (Rangpani) Zero Point, Sugondha Sea Beach, Sunset Point Kuakata, T-Badh, Tajhat Palace, Tanguar Haor, Tara Masjid (Star Mosque), The Sundarbans, Tilagor Eco Park, Varendra Research Museum, Vinno Jogot Amusement Park, Zainul Abedin Park
- phase5 manual review sample: 0/50 pairs carry a human_label
