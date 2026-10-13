# **Iron & Oak Provision Co. — Business Profile & Knowledge Base Architecture**

# **1\. Brand Identity & Marketing Profile**

## **Overview**

Iron & Oak Provision Co. is a heritage outdoor workwear and handcrafted leather goods manufacturer dedicated to producing functional, durable gear designed for long-term field use.

| Attribute | Specification |
| :---- | :---- |
| **Company Name** | Iron & Oak Provision Co. |
| **Tagline / Slogan** | Built for the Trail. Proven for a Lifetime. |
| **Industry** | Heritage Apparel, Leather Goods & Outdoor Utility Gear |
| **Target Demographic** | Tradespeople, carpenters, field biologists, backcountry campers, and heritage apparel enthusiasts (Ages 24–55) |
| **Core Values** | Uncompromising Durability, Radical Repairability, Stewardship & Traceability |

## **Mission Statement**

Iron & Oak Provision Co. creates rugged, heirloom-grade apparel, handcrafted leather goods, and outdoor utility gear designed to endure decades of demanding use. Through sustainable, ethical craftsmanship and a lifetime repair ethos, we empower outdoor workers, adventurers, and craftsmen to consume less by owning gear that never quits.

## **Brand Story & Values**

* **Uncompromising Durability:** Every garment and leather good is constructed using heavy-gauge canvas, full-grain vegetable-tanned leather, and solid brass hardware. We design our items to resist abrasion, severe weather, and physical stress.  
* **Radical Repairability:** We reject planned obsolescence. Products feature modular seams, exposed stress points, and repairable hardware, ensuring items can be serviced repeatedly over decades rather than discarded.  
* **Stewardship & Traceability:** Sourcing is restricted to transparent supply chains, including domestic American hides, organic waxed cotton canvas, and certified conflict-free metal hardware.

## **Tone & Voice Guidelines**

* **Pragmatic & Direct:** Clear, factual descriptions focused on utility, performance, and material specifications.  
* **Confident & Knowledgeable:** Speaks with the authority of experienced tradespeople and gear smiths.  
* **Warm & Honest:** Approachable and respectful without relying on marketing hype, buzzwords, or exaggerated claims.

---

# **2\. Documentation & Knowledge Base Breakdown**

## **A. Lifetime Warranty & Repair Intake Protocol**

* **Recommended File Format:** `REPAIR_POLICY.md` (Markdown)  
* **Rationale:** Clean, structural format easily rendered in developer/system repos, customer portals, or terminal CLI tools.  
* **Comprehensive Contents & Specification Blueprint:**  
  * **Iron & Oak Heritage Guarantee Scope:** Coverage against structural failures, split seams, broken rivets, zipper blowouts, and leather hardware failures caused by regular field use.  
  * **Exclusions & Limitations:** Deliberate abuse, extreme neglect (mold, pet chewing, prolonged submersion), unauthorized third-party modifications, and cosmetic patina/scuffs.  
  * **Standard Repair Intake Workflow:** Step-by-step submission process, photo pre-assessment via customer intake portal, RMA (Return Merchandise Authorization) generation.  
  * **Shipping & Turnaround:** Customer covers initial incoming shipping; company covers repair labor, materials, and return ground shipping. Average repair cycle is 10 to 14 business days.  
  * **Beyond Repair Replacement Option:** When structural repair compromises safety or integrity, customers receive a 40% trade-in credit toward a replacement item.

```xml
## 1. Iron & Oak Heritage Guarantee Scope

| Covered Under Guarantee | Excluded / Non-Covered |
| :--- | :--- |
| Structural seam splits and blown stitching | Normal wear, cosmetic patina, and surface scuffs |
| Broken brass rivets, snaps, and buckles | Mold, pet damage, and extreme chemical exposure |
| Zipper teeth failure and runner separates | Unauthorized third-party modifications |

## 2. 5-Step Repair Submission Workflow

1. **Photo Triage:** Submit clear photos via customer intake portal.
2. **RMA Issuance:** Receive Return Merchandise Authorization within 24 hours.
3. **Incoming Shipping:** Ship gear to our bench workshop (customer covers incoming shipping).
4. **Bench Repair:** Craftsmen repair item using original heavy-gauge thread and solid brass hardware (10–14 business days).
5. **Return Shipping:** Restored item returned with complimentary ground freight.

## 3. Beyond Repair & 40% Trade-In Policy

When an item is damaged beyond functional repair, customers receive a **40% trade-in credit** toward a replacement gear purchase while we recycle usable hardware.
```

## **B. Leather & Waxed Canvas Care Guide**

* **Recommended File Format:** `CARE_GUIDE.md` (Markdown)  
* **Rationale:** Clean, structured document formatting easily maintained in documentation repos and renderable across web portals and developer hubs.  
* **Comprehensive Contents & Specification Blueprint:**  
  * **Leather Conditioning Schedules:** Recommendations for biannual application of beeswax/neatsfoot oil balms depending on climate dryness and humidity.  
  * **Cleaning Protocols:** Damp cloth wiping, saddle soap treatments for deep mud/grease, and strict prohibitions against machine washing or heat drying.  
  * **Waxed Canvas Rewaxing Procedure:** Annual or seasonal spot rewaxing steps utilizing heat guns/hairdryers and paraffin/beeswax bars to restore water resistance.  
  * **Storage Recommendations:** Breathable canvas bags, ambient moisture control, avoiding direct UV sunlight during off-season storage.

```xml
## 1. Vegetable-Tanned Leather Maintenance

- **Biannual Conditioning:** Apply natural beeswax or neatsfoot oil balms every 6 months to prevent dry cracking.
- **Cleaning Protocol:** Wipe with a damp cloth; use saddle soap sparingly for deep mud or grease removal.
- **Prohibitions:** *Strictly no machine washing or heat drying.* High temperature strips natural oils and distorts grain.

## 2. Waxed Canvas Rewaxing Procedure

1. Clean surface debris using cold water and a soft brush.
2. Apply a paraffin/beeswax bar evenly across canvas weave using circular motions.
3. Use a heat gun or hairdryer on medium heat to melt wax deep into fibers.
4. Allow canvas to cure in a cool dry area for 24 hours.

## 3. Off-Season Storage

Store gear in breathable canvas storage bags in well-ventilated spaces. Avoid direct UV sunlight and damp basements to prevent mold growth and leather degradation.
```

## **C. Standard Sizing & Field Fit Chart**

* **Recommended File Format:** `sizing_specs.json` (JSON formatted with 4-space indentation)  
* **Rationale:** Structured data format representing dimensional measurements, fit definitions, tabular relationship matrices, and SKU size mappings for seamless backend integration and API querying.  
* **Comprehensive Contents & Specification Blueprint:**  
  * **Apparel Measurement Matrix:** Chest, sleeve, shoulder, and waist measurements for chore coats, heavy wool overshirts, and canvas utility pants (sizes XS to 3XL).  
  * **Field Fit vs. Tailored Fit Definitions:** Operational explanation of layering allowances (e.g., room for thermal base layers and midweight knits underneath).  
  * **Leather Goods Sizing:** Belt measurement guidelines (ordering two inches above trouser waist size) and boot footbed sizing notes.  
  * **Custom Tailoring Disclaimer:** Policies on custom sleeve hem requests and their impact on standard return windows.

```json
{
    "sizing_metadata": {
        "brand": "Iron & Oak Provision Co.",
        "version": "1.2",
        "units": "inches",
        "measurement_disclaimer": "Measurements correspond to garment dimensions. Field Fit accommodates midweight thermal underlayers."
    },
    "products": [
        {
            "sku": "APP-CC-001",
            "name": "Timberline Waxed Chore Coat",
            "category": "Outerwear",
            "fit_profile": "Field Fit (relaxed through shoulders and chest)",
            "size_matrix": {
                "S": { "chest": 42, "sleeve": 34.5, "shoulder": 18.5, "length": 29 },
                "M": { "chest": 45, "sleeve": 35.5, "shoulder": 19.5, "length": 30 },
                "L": { "chest": 48, "sleeve": 36.5, "shoulder": 20.5, "length": 30.5 },
                "XL": { "chest": 51, "sleeve": 37.0, "shoulder": 21.5, "length": 31 }
            }
        },
        {
            "sku": "LTH-BLT-004",
            "name": "Standard Field Belt (1.5 Inch)",
            "category": "Leather Accessories",
            "fit_profile": "Order 2 inches above standard trouser waist size",
            "size_matrix": {
                "32": { "center_hole_length": 34, "total_length": 39, "width": 1.5 },
                "34": { "center_hole_length": 36, "total_length": 41, "width": 1.5 },
                "36": { "center_hole_length": 38, "total_length": 43, "width": 1.5 }
            }
        }
    ]
}
```

## **D. Customer Order, Exchange & Return Policy**

* **Recommended File Format:** `RETURNS_AND_EXCHANGES.md` (Markdown)  
* **Rationale:** Clear, accessible customer-facing policy document easily rendered across platforms and customer service portals.  
* **Comprehensive Contents & Specification Blueprint:**  
  * **45-Day Field Trial Period:** Returns accepted in unwashed, original condition for full refunds to original payment method.  
  * **Exchange Shipping:** Prepaid digital return labels provided for domestic size/color exchanges.  
  * **Final Sale Items:** Factory seconds, custom monogrammed leather, and archived sale batches designated as final sale.  
  * **Restocking Fees & Processing:** Zero restocking fees; return inspections processed within 3 business days of warehouse receipt.

```xml
## 1. 45-Day Field Trial Guarantee

Test your gear for up to 45 days. Items returned in unwashed, original condition with tags attached receive full refunds to original payment methods.

## 2. Exchanges & Digital Return Labels

Complimentary prepaid digital shipping labels are generated automatically via our customer portal for all domestic size and color exchanges.

## 3. Final Sale Exclusions

Custom monogrammed leather goods, altered sleeve hems, and factory seconds are non-returnable and excluded from refund policies.
```

## **E. B2B Wholesale & Commercial Fleet Procurement SOP**

* **Recommended File Format:** `WHOLESALE_SOP.md` (Markdown)  
* **Rationale:** Structured standard operating procedure (SOP) tailored for operational teams, account managers, and corporate client portals.  
* **Comprehensive Contents & Specification Blueprint:**  
  * **Minimum Order Quantities (MOQ):** Tiered thresholds (Tier 1: 25 units; Tier 2: 100+ units; Tier 3: 500+ units) for corporate outfits and outfitter partners.  
  * **Co-Branding & Custom Stamping:** Debossing guidelines, vector logo submission standards, and tool-and-die setup fees.  
  * **Payment Terms & Invoicing:** Net-30 credit terms upon credit check approval, 50% deposit required for customized corporate batches.  
  * **Lead Times & Fulfillment Logistics:** Standard 4 to 6 week manufacturing schedules, freight forwarding arrangements, and volume shipping freight policies.

```xml
## 1. Tiered Minimum Order Quantities (MOQ)

- **Tier 1 (25–99 units):** 40% discount off MSRP
- **Tier 2 (100–499 units):** 48% discount off MSRP
- **Tier 3 (500+ units):** 55% discount off MSRP

## 2. Custom Branding & Debossing Guidelines

Hot-stamp custom logo debossing is available across all leather goods. Vector files (.AI or .PDF) are required. A one-time **$150 tool-and-die brass mold fee** applies per custom artwork submission.

## 3. Payment Terms & Production Schedules

- **Payment Terms:** Net-30 terms upon approved credit evaluation; 50% deposit required on custom co-branded production batches.
- **Manufacturing Lead Time:** Standard 4 to 6 week production window from deposit receipt to freight delivery.
```

## **F. Master Customer Support FAQ Knowledge Base**

* **Recommended File Format:** `faq_support_knowledgebase.json` (JSON formatted with 4-space indentation)  
* **Rationale:** Structured JSON knowledge base ready for programmatic ingestion, vector database chunking, or RAG chatbot agent pipelines.  
* **Comprehensive Contents & Specification Blueprint:**  
  * Categorized Question-and-Answer pairs across all core business operations:  
    1. Order status, shipping speed, and tracking.  
    2. Warranty claims, repair RMA tracking, and repair vs. replacement evaluation.  
    3. Product materials, ethical leather sourcing, and water resistance specifications.  
    4. Garment care mistakes, stain removal, and conditioning frequencies.  
    5. Corporate gifting, tax exemption handling, and volume discounts.

```json
{
    "knowledgebase_metadata": {
        "company": "Iron & Oak Provision Co.",
        "system_id": "KB-IO-2024-V1",
        "total_entries": 5
    },
    "faqs": [
        {
            "id": "FAQ-REP-001",
            "category": "Warranty & Repair",
            "question": "What is covered under the Iron & Oak Heritage Guarantee?",
            "answer": "Our Heritage Guarantee covers structural failures, blown seams, detached rivets, zipper teeth failure, and broken brass hardware resulting from regular field use for the lifetime of the product. It excludes aesthetic patina, deliberate abuse, pet damage, and unauthorized third-party alterations.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-SIZ-002",
            "category": "Sizing & Fit",
            "question": "How should I select the right belt size?",
            "answer": "We recommend ordering your belt two inches larger than your standard pant waist size (e.g., if you wear a 34-inch trouser, order a size 36 belt). This ensures the buckle tongue fastens at the center hole of the five sizing holes.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-WHO-003",
            "category": "Wholesale & B2B",
            "question": "Can we deboss our company logo onto wholesale leather field notebooks?",
            "answer": "Yes. We offer custom hot-stamp debossing on orders meeting our Tier 1 MOQ of 25 units. A one-time $150 brass die tooling fee applies, and artwork must be supplied as a vectorized PDF or AI file.",
            "escalate_to_human": false
        }
    ]
}
```