# Data quality notes

Before trusting any number from the GA4 sample, I checked the raw events for tracking problems. Four turned up. Each one is handled in the pipeline and documented here so the numbers in the dashboards can be traced back.

Run `python python/scripts/headline_facts.py` to reprint every figure below from the warehouse.

## 1. Duplicate purchase events

GA4 sometimes records the same purchase more than once, for example when someone reloads the confirmation page. 404 of the 5,692 purchase events were repeats.

- Fix: keep the first event per order (`int_ga4__purchases_deduped`).
- Impact: raw revenue of $362.2k is overstated by $23.8k, or 7.0%.

## 2. Purchases without a transaction ID (11 days, mostly early November)

On 11 days no purchase had a transaction ID at all, and on most other days a handful were missing. That's 906 events in total, about half of them in the first two weeks of November. My first version of the pipeline dropped these, because without an ID they can't be checked for duplicates. That quietly removed early-November sales from every report.

- Fix: for purchases with no ID, treat events in the same session, with the same amount and the same basket, as one order. That keeps 837 orders worth $30.7k.
- Limitation: tested on orders that do have IDs, this rule merges about 3.6% of genuine repeat orders (someone buying the same thing twice in one visit), so the recovered count may be slightly low.
- What changed when I fixed it: revenue went from $307.6k to $338.3k, orders from 4,451 to 5,288, and conversion from 1.24% to 1.47%. Earlier I said duplicates inflated revenue by 18%. That was wrong: it mixed the duplicates (7%) with these dropped orders.

## 3. The add-to-cart tag stopped firing (22 days in November)

On a normal day there are 1.1 to 2.3 add-to-cart events for every checkout started. From 1 to 24 November the tag was broken on 22 days: often zero add-to-cart events while hundreds of people were still checking out. Nobody can check out without a cart, so the tag simply wasn't firing.

- Fix: days where add-to-cart events fall below 0.6 per checkout are flagged (`dim_date.is_cart_tracking_ok`), and the funnel is calculated on the other 70 days only.
- Impact: product view to cart goes from 19.7% to 25.7%, and cart to checkout from 73.1% to 53.1%. The old cart to checkout figure was inflated because carts were under-counted.

## 4. Purchase values stopped being recorded (26 to 31 January)

Orders kept coming in at a normal rate (about 50 a day), but from 26 January the value attached to each purchase collapses: the average order drops from about $60 to $24, then $9, $2, $4, $5 and finally $0. The tag was still firing, just without the right amount.

- Fix: days whose average purchase value is under half the typical day's are flagged (`dim_date.is_revenue_tracking_ok`). Order counts and conversion rates are unaffected and still use all days.
- Impact: roughly $12k to $16k of January revenue is missing from the totals (about 260 orders). Comparing like for like, January earned $2,174 a day against December's $5,101: 57% lower, not the 64% you get from the raw monthly totals.

## 5. Things that can't be fixed

- Timestamps were scrambled when Google anonymised the sample: sessions are spread evenly across all 24 hours, including 3am. So there's no time-of-day analysis in this project. Day of week does show a real pattern and is used instead.
- About 9% of traffic sources are hidden (`<Other>`, `(data deleted)`) and kept as "Obfuscated".
- Users are identified by browser cookie, so cross-device journeys are split.
- Product-view and add-to-cart events each list about 11 products instead of the one viewed or added, so they can't show which product someone looked at. Product analysis uses purchases only (`eda.md`).
