# **Cinder & Salt Bakery — Business Profile & Knowledge Base Architecture**

# **1\. Brand Identity & Marketing Profile**

* 

| Attribute | Specification |
| :---- | :---- |
| Company Name | Cinder & Salt Bakery |
| Tagline / Slogan | Wild Yeast. Heritage Grain. Honest Craft. |
| Industry | Artisanal Sourdough Bakery, Regional Stone Milling & Commercial Food Service |
| Target Demographic | Health-conscious households prioritizing gut health, farm-to-table restaurant chefs, specialty café buyers, and couples seeking rustic event catering (Ages 25–60). |
| Core Values | 100% Wild Fermentation, Regional Grain Stewardship, Radical Allergen Transparency |

## **Mission Statement**

Cinder & Salt Bakery crafts naturally leavened artisan breads, heritage grain pastries, and bespoke wholesale offerings rooted in regional agriculture and patient fermentation. We marry old-world breadcraft with strict allergen transparency, delivering wholesome sustenance and culinary integrity without industrial shortcuts, chemical improvers, or commercial yeast.

## **Brand Story & Values**

* **Pure Wild Fermentation & Digestive Wellness:** Every loaf relies exclusively on a single heritage sourdough starter culture nurtured since day one. Long cold-fermentation cycles (24 to 36 hours) break down complex starches and phytic acid, unlocking bioavailability and creating bread that is naturally easier on digestion.  
* **Regional Agronomy & Stone Milling:** We partner directly with regenerative dryland grain growers across the region. Grains such as Red Fife, Spelt, Dark Northern Rye, and Einkorn are stone-milled in-house weekly to retain the nutrient-rich germ and essential oils stripped by commercial roller mills.  
* **Radical Food Integrity & Allergen Honesty:** We operate with zero hidden additives, dough conditioners, or artificial stabilizers. We maintain clear boundaries regarding allergen risks, offering detailed ingredient tracing and transparent cross-contact guidance so customers can make informed dietary decisions.

## **Tone & Voice Guidelines**

* **Warm & Hospitable:** Approachable, inviting, and passionate about feeding the local community.  
* **Artisanal & Scientific:** Balances culinary artistry with precise food science (hydration percentages, fermentation microbiology, baking temperatures).  
* **Direct & Transparent:** Clear, uncompromising communication regarding allergen disclosures, order cutoffs, and production capacities.

---

# **2\. Documentation & Knowledge Base Breakdown**

## **A. Allergen Safety & Kitchen Cross-Contact Protocols**

* **Recommended File Format:** `ALLERGEN_SAFETY_PROTOCOL.md` (Markdown)  
* **Rationale:** Clean, structural standard operating procedure for kitchen staff, customer inquiries, and commercial regulatory compliance.  
* **Specification Blueprint:**

```
# STANDARD OPERATING PROCEDURE: Allergen Safety & Cross-Contact Protocols

## 1. Airborne Flour & Celiac Safety Notice
Cinder & Salt Bakery operates an open-concept bakery and active stone mill. We mill whole grains (wheat, rye, spelt, einkorn) on-site.
- **Gluten Presence:** Fine flour particles remain airborne throughout the facility 24 hours a day.
- **Celiac Disclaimer:** While we offer items prepared without gluten-containing ingredients, **our facility is NOT celiac-safe**. We do not produce certified gluten-free products. Customers with Severe Gluten Intolerance, Celiac Disease, or Wheat Allergies should not consume our products.

## 2. Allergen Matrix & Kitchen Separation
The following major allergens are processed on shared equipment within our production facility:
| Allergen | Present in Facility | Dedicated Equipment Used | Storage Protocols |
| :--- | :--- | :--- | :--- |
| **Gluten / Wheat** | Yes (Primary) | No | Open bin storage |
| **Tree Nuts** | Yes (Walnuts, Almonds) | Yes (Color-coded Red) | Sealed lug containers |
| **Sesame** | Yes | Yes (Color-coded Yellow) | Labeled ingredient bins |
| **Dairy** | Yes (Butter, Milk, Cheese) | Yes (Color-coded Blue) | Dedicated refrigeration shelf |
| **Eggs** | Yes | Yes (Color-coded Blue) | Bottom-shelf refrigeration |

## 3. Daily Sanitization & Production Sequence Runbook
To minimize allergen cross-contact, production must follow a strict sequential schedule:
1. **02:00 AM – Pure / Seedless Bakes:** Plain sourdoughs (Country White, Spelt Boule) shaped and baked first.
2. **04:00 AM – Enriched & Seeded Bakes:** Seeded loaves (Seeded Rye, Sesame Baguettes) and nut pastries processed second.
3. **12:00 PM – Mid-Day Sanitation:** All mixers, benches, and proofing baskets undergo scrapedown and sanitization.
4. **08:00 PM – End-of-Shift Washdown:** 3-compartment sink wash (200 PPM quaternary ammonium), steam sanitization of racks, HEPA vacuuming of mill housing.

## 4. Allergen Incident Escalation Workflow
1. **Halt Production:** Flag affected batch with RED "ALLERGEN CONTAMINATED" tape.
2. **Log Incident:** Record batch number, time, and cross-contact source in Kitchen Shift Log.
3. **Repurpose or Dispose:** Batch cannot be sold under standard labeling.
4. **Notification:** Inform Head Baker and Quality Lead before shift conclusion.
```

## **B. Wholesale Partner Procurement & Delivery SOP**

* **Recommended File Format:** `WHOLESALE_ORDERING_GUIDE.md` (Markdown)  
* **Rationale:** Operational agreement governing business-to-business relationships with local restaurants, coffee shops, and specialty grocers.  
* **Specification Blueprint:**

```
# WHOLESALE PARTNER PROCUREMENT & DELIVERY GUIDE

## 1. The 48-Hour Fermentation Lead Time Rule
Our sourdough breads undergo a mandatory 24-to-36-hour cold fermentation cycle. Because we do not use commercial yeast or dough accelerants, **all wholesale orders require a strict 48-hour advance notice**.
- **Standing Order Freeze:** Standing orders lock at **2:00 PM** two days prior to delivery.
- **Order Modifications:** Additions or reductions must be submitted via the B2B Portal before the 2:00 PM cutoff. Late modifications cannot be accommodated.

| Order Placed By (2:00 PM) | Fermentation & Proofing Window | Delivery Window |
| :--- | :--- | :--- |
| **Sunday** | Monday | **Tuesday Morning** |
| **Monday** | Tuesday | **Wednesday Morning** |
| **Tuesday** | Wednesday | **Thursday Morning** |
| **Wednesday** | Thursday | **Friday Morning** |
| **Thursday** | Friday | **Saturday Morning** |
| **Friday** | Saturday | **Sunday Morning** |

*Note: Kitchen and delivery routes are closed on Mondays.*

## 2. Minimum Order Values & Regional Routes
- **Minimum Order Value (MOV):** $75.00 per delivery drop. Orders below $75.00 incur a $15.00 small-drop surcharge.
- **Delivery Schedule:** Tuesday through Sunday, 4:30 AM – 7:00 AM.
- **Delivery Zones:** Zone A (Urban Core) receives daily drops (Tue–Sun); Zone B (Outer Metro) receives Tue/Thu/Sat drops.

## 3. Unassisted Delivery & Storage Protocols
- **Access Requirements:** Partners must supply a reliable keycode or lockbox key for entry.
- **Drop Location:** Drops are made directly to partner's designated walk-in cooler or food-safe staging counter.
- **Cold Weather Protection:** During winter months (Nov 1 – Apr 1), exterior lockbox drops are strictly prohibited to prevent thermal shock.

## 4. Invoicing, Terms & Quality Claims
- **Payment Terms:** Net-15 via automated ACH through wholesale portal. Invoices generate upon delivery departure.
- **Quality Claims:** Missing, damaged, or unsatisfactory items must be reported within **12 hours of delivery drop** with cross-section photos.
```

## **C. Daily Production & Bake Schedule Specifications**

* **Recommended File Format:** `daily_bake_matrix.json` (JSON formatted with 4-space indentation)  
* **Rationale:** Relational data structure detailing recipes, production volumes, and scheduling parameters for kitchen management and programmatic POS/inventory integration.  
* **Specification Blueprint:**

```json
{
    "bakery_metadata": {
        "facility": "Cinder & Salt Bakery - Main Production Facility",
        "version": "2.4",
        "last_updated": "2024-10-15",
        "operating_days": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    },
    "production_catalog": [
        {
            "sku": "BRD-CS-001",
            "item_name": "Country Sourdough Boule",
            "category": "Bread",
            "flour_profile": "70% Organic Hard Red Wheat, 20% Stone-Milled Red Fife, 10% Whole Rye",
            "hydration_percentage": 78,
            "bulk_fermentation_hours": 5.5,
            "cold_hours": 24,
            "target_baked_weight_grams": 850,
            "active_bake_days": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "base_retail_price": 9.50,
            "wholesale_price_tiers": {
                "tier_1_standard": 6.25,
                "tier_2_volume": 5.75
            },
            "daily_par_limits": {
                "weekday": 120,
                "weekend": 220
            }
        },
        {
            "sku": "BRD-SR-002",
            "item_name": "Seeded Dark Rye",
            "category": "Bread",
            "flour_profile": "60% Whole Dark Northern Rye, 40% High Gluten Wheat",
            "hydration_percentage": 84,
            "bulk_fermentation_hours": 4.0,
            "cold_hours": 36,
            "target_baked_weight_grams": 900,
            "active_bake_days": ["Tuesday", "Thursday", "Saturday", "Sunday"],
            "base_retail_price": 10.50,
            "wholesale_price_tiers": {
                "tier_1_standard": 7.00,
                "tier_2_volume": 6.50
            },
            "daily_par_limits": {
                "weekday": 45,
                "weekend": 85
            }
        }
    ]
}
```

## **D. Custom Event & Bespoke Cake Ordering Policy**

* **Recommended File Format: CATERING\_AND\_CUSTOM\_CAKES.md (Markdown)**  
* **Rationale: Customer-facing policy and planner intake guidelines for weddings, corporate gatherings, and seasonal events.**  
* **Specification Blueprint:**

```
# CUSTOM EVENTS & BESPOKE CAKE ORDERING POLICY

## 1. Booking Lead Times
- **Weddings & Large Events (100+ guests):** Minimum **6 weeks** notice required. Peak season dates (May–October) close up to 6 months in advance.
- **Bespoke Celebratory Cakes:** Minimum **14 days** notice required.
- **Small Wholesale Event Trays:** Minimum **7 days** notice required.

## 2. Tasting Consultations & Box Pickups
- **Fee:** $45.00 per tasting box (includes 4 sourdough cake options and 3 seasonal buttercreams/preserves).
- **Credit:** The $45.00 fee is credited toward any final catering contract exceeding **$300.00**.
- **Pickup Schedule:** Prepared on the 1st and 3rd Saturday of every month between 10:00 AM and 1:00 PM.

## 3. Deposit, Payment & Cancellation Schedule
- **Deposit:** 50% non-refundable deposit required at contract signing to reserve event date.
- **Final Balance:** Remaining balance must be paid in full 14 days prior to event date.
- **Cancellations:** 30+ days prior: deposit retained; 14–29 days prior: 50% contract value retained; under 14 days: 100% contract value retained.

## 4. Temperature Handling & Outdoor Setup Rules
- **Temperature Threshold:** Swiss meringue buttercream softens at 72°F (22°C) and collapses above 80°F (27°C).
- **Outdoor Display Limit:** Outdoor displays in temperatures above **72°F (22°C)** are strictly limited to **2 hours maximum**.
- **Direct Sunlight:** Cakes must remain in complete shade. Direct sunlight induces collapse within 15 minutes.
```

## **E. Loaf Care, Storage & Revival Guide**

* **Recommended File Format: BREAD\_STORAGE\_AND\_REVIVAL.md (Markdown)**  
* **Rationale: Educational consumer guide explaining the mechanics of bread staling and how to maximize the shelf life of preservative-free sourdough.**  
* **Specification Blueprint:**

```
# LOAF CARE, STORAGE & REVIVAL GUIDE

## 1. The Science of Staling: Why Refrigeration Is Forbidden
Commercial bread uses mono- and diglycerides and chemical preservatives. Cinder & Salt sourdough contains only flour, water, and sea salt.
- **Starch Retrogradation:** Staling occurs when starch molecules recrystallize and expel moisture from the crumb.
- **The Refrigerator Trap:** Refrigeration temperatures (35°F–42°F / 1°C–5°C) **accelerate retrogradation by up to 300%**. *Never store fresh artisan bread in the refrigerator.*

## 2. Storage Timeline: Counter vs. Freezer
- **Days 1–2:** Place loaf cut-side down directly on a wooden cutting board at room temperature.
- **Days 3–5:** Transfer loaf into an unbleached linen bread bag or brown paper sack. Avoid airtight plastic bags.
- **Long-Term Storage (Up to 3 Months):** Slice entire loaf, place parchment squares between slices, and freeze inside a sealed freezer bag at 0°F (-18°C).

## 3. The 5-Minute Oven Refresh Technique
1. **Preheat Oven:** Set oven to **375°F (190°C)**.
2. **Moisten the Crust:** Run the entire unsliced stale loaf under cold tap water for 3 to 5 seconds. Do not soak.
3. **Bake:** Place wet loaf directly on the center oven rack for **6 to 8 minutes**.
4. **Rest:** Allow loaf to rest for 5 minutes before slicing. Steam gelatinizes interior crumb while crisping the crust.
```

## **F. Master Customer Support FAQ Knowledge Base**

* **Recommended File Format: faq\_support\_knowledgebase.json (JSON formatted with 4-space indentation)**  
* **Rationale: Structured JSON knowledge base ready for programmatic ingestion, vector database chunking, or RAG chatbot agent pipelines.**  
* **Specification Blueprint:**

```json
{
    "knowledgebase_metadata": {
        "company": "Cinder & Salt Bakery",
        "system_id": "KB-CS-2024-V1",
        "total_entries": 5
    },
    "faqs": [
        {
            "id": "FAQ-ALG-001",
            "category": "Allergens & Ingredients",
            "question": "Are your sourdough breads safe for someone with Celiac Disease?",
            "answer": "No. While our 24-36 hour wild fermentation process breaks down gluten starches making it easier to digest for gluten-sensitive individuals, our facility actively stone-mills grains on-site. Airborne flour particles are present throughout the bakery. We are NOT a certified celiac-safe environment.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-RET-002",
            "category": "Daily Retail & Pre-Orders",
            "question": "What time do you usually sell out of Country Sourdough?",
            "answer": "Our daily counter supply generally sells out between 11:30 AM and 1:00 PM on weekdays, and often before 11:00 AM on weekends. We strongly recommend placing a pre-order through our website 48 hours in advance to guarantee your items.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-WHO-003",
            "category": "Wholesale Accounts",
            "question": "Can I modify my wholesale delivery order for tomorrow morning?",
            "answer": "All wholesale orders must adhere to our 48-hour fermentation lead time. Standing order modifications for tomorrow morning locked today at 2:00 PM. Any changes requested past 2:00 PM cannot be processed as our doughs are already in their final fermentation cycle.",
            "escalate_to_human": true
        },
        {
            "id": "FAQ-STR-004",
            "category": "Bread Care & Storage",
            "question": "Should I keep my sourdough loaf in the refrigerator?",
            "answer": "Never refrigerate fresh artisan bread. Refrigerator temperatures accelerate starch retrogradation, causing the bread to dry out and go stale three times faster. Store cut-side down on a wooden board or in a paper bag at room temperature.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-CAT-005",
            "category": "Catering & Events",
            "question": "How far in advance do I need to book a wedding cake or dessert table?",
            "answer": "We require a minimum of 6 weeks notice for wedding orders and large event catering, and 14 days notice for smaller custom celebratory cakes. Peak wedding season dates (May-October) fill rapidly, so early booking is recommended.",
            "escalate_to_human": false
        }
    ]
}
```

---


