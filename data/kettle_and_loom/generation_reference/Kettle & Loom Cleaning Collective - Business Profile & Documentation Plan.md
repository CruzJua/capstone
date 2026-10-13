# **Kettle & Loom Cleaning Collective — Business Profile & Knowledge Base Architecture**

# **1\. Brand Identity & Marketing Profile**

| Attribute | Specification |
| :---- | :---- |
| **Company Name** | Kettle & Loom Cleaning Collective |
| **Tagline / Slogan** | Pure Ingredients. Meticulous Spaces. Uncompromising Clean. |
| **Industry** | Commercial Janitorial, Turnover Cleaning & Residential Property Services |
| **Target Demographic** | Eco-conscious homeowners, short-term rental property managers (Airbnb/VRBO), architectural design firms, commercial office managers, and post-construction general contractors (Ages 25–65). |
| **Core Values** | Non-Toxic Plant & Mineral Chemistry, Zero-VOC Air Quality, W-2 Worker Collective & Living Wages |

## **Mission Statement**

Kettle & Loom Cleaning Collective delivers high-performance residential turnover, post-construction remediation, and recurring commercial janitorial services using zero-VOC, hospital-grade botanical formulations. We protect indoor air quality and client health while delivering spotless, hospitality-ready spaces backed by rigorous, transparent inspection protocols.

## **Brand Story & Core Pillars**

* **Botanical Chemistry & Zero-VOC Indoor Air Quality:** We replace petrochemical bleaches, synthetic fragrances, and caustic ammonias with thymol, hydrogen peroxide, and organic citric acid formulations that leave spaces clean without toxic residue or respiratory hazards.  
* **Hospitality & Turnover Precision:** From short-term rental turnovers to multi-phase post-construction drywall dust extraction, our standardized room-by-room workflows ensure consistent, audit-ready cleanliness.  
* **Worker Collective & Professional Care:** We operate as a living-wage cooperative of professional W-2 cleaning specialists. High retention among our cleaning staff directly translates to trusted, familiar technicians caring for clients' spaces.

## **Tone & Voice Guidelines**

* **Wholesome & Hospitable:** Clean, reassuring, and dedicated to health and environmental wellness.  
* **Methodical & Detail-Oriented:** Emphasizes precision, hygiene standards, and systematic inspection runbooks.  
* **Professional & Transparent:** Upfront about access requirements, chemical disclosures, cancellation timelines, and service scopes.

# **2\. Documentation & Knowledge Base Breakdown**

## **A. Chemical Safety Data Sheet (SDS) & Botanical Chemistry Guidelines**

* **Recommended File Format:** `CHEMICAL_SAFETY_AND_SDS_GUIDE.md` (Markdown)  
* **Rationale:** Clean, structural standard operating procedure ensuring OSHA and EPA compliance, worker safety, and client peace of mind regarding non-toxic products.  
* **Specification Blueprint:**

```
# STANDARD OPERATING PROCEDURE: Chemical Safety & Botanical Chemistry Guidelines

## 1. Approved Botanical Formulations & Active Ingredients

Kettle & Loom exclusively deploys EPA Design for the Environment (DfE) and Green Seal certified cleaning chemistry:

| Product / Formulation | Active Botanical Base | Target Pathogens / Soils | Dwell Time Required |
| :--- | :--- | :--- | :--- |
| **Bio-Shield Hospital Disinfectant** | Thymol (0.05% botanical thyme extract) | 99.99% bacteria, enveloped viruses, fungi | 10 minutes (wet dwell) |
| **OxyPure Multi-Surface Cleaner** | Hydrogen Peroxide (stabilized 3%) | Soap scum, organic grease, protein soils | 3 minutes |
| **Citrus-Loom Mineral Descaler** | Organic Citric Acid (food-grade 8%) | Hard water scale, calcium deposits, rust | 5 minutes |
| **PureLoom Floor Wash** | Saponified Coconut & Olive Oil Soap | Hardwood, engineered plank, stone tiles | Immediate mop dry |

## 2. Stone & Surface Material Compatibility Warnings

* **Strict Acid Prohibition:** *Citrus-Loom Descaler and acidic solutions must NEVER be applied to unsealed natural marble, travertine, limestone, or terrazzo.* Acid etching permanently damages calcite stone.
* **Hardwood Neutrality:** Wood flooring must be cleaned exclusively with pH-neutral PureLoom wash; never saturated with standing water.

## 3. SDS Exposure Protocols & First Aid

* **Inhalation:** Non-hazardous; zero-VOC formulation eliminates toxic vapor buildup.
* **Eye Contact:** In case of direct splash, flush eyes with potable water for 10 minutes.
* **Storage & Dilution:** All botanical concentrates must remain in labeled, UV-resistant amber dispensers at 50°F–80°F (10°C–27°C).
```

\#\# 1\. Approved Botanical Formulations & Active Ingredients

## **B. Commercial Janitorial & Turnover Service Scope Matrix**

* **Recommended File Format:** `service_scope_matrix.json` (JSON formatted with 4-space indentation)  
* **Rationale:** Relational data structure detailing room zones, task checklists, frequency flags, and estimated labor times for programmatic scheduling and quoting engines.  
* **Specification Blueprint:**

```json
{
    "scope_matrix_metadata": {
        "company": "Kettle & Loom Cleaning Collective",
        "standard_version": "3.1",
        "currency": "USD",
        "base_hourly_rate_per_tech": 55.00
    },
    "service_tiers": [
        {
            "tier_id": "TIER-RES-01",
            "tier_name": "Standard Residential Maintenance",
            "frequency_options": [
                "Weekly",
                "Bi-Weekly",
                "Monthly"
            ],
            "zones": {
                "kitchen": [
                    "Wipe exterior cabinet faces and drawer pulls",
                    "Sanitize countertops and backsplash with OxyPure",
                    "Clean and polish exterior stainless steel appliances",
                    "Scrub sink basin, aerator, and faucet fixture",
                    "Vacuum and damp-mop hard surface floors"
                ],
                "bathrooms": [
                    "Scrub shower tile grout and sanitize fiberglass tubs",
                    "Disinfect toilet bowl, tank, base, and flush lever",
                    "Polish vanity mirrors and clean medicine cabinet fronts",
                    "Wipe down light fixtures and exhaust fan covers"
                ]
            },
            "estimated_minutes_per_1000_sqft": 75
        },
        {
            "tier_id": "TIER-TRN-02",
            "tier_name": "Hospitality Short-Term Rental Turnover",
            "frequency_options": [
                "Per Turnover Checkout"
            ],
            "zones": {
                "guest_readiness": [
                    "Strip and launder bed linens and towels with hypoallergenic wash",
                    "Make beds to hotel hospital-corner standard",
                    "Restock guest amenities (botanical soaps, organic coffee pods)",
                    "Sanitize high-touch surfaces (remotes, keypad deadbolts, thermostats)",
                    "Inspect under furniture and in closets for left-behind guest property"
                ]
            },
            "estimated_minutes_per_1000_sqft": 110
        }
    ]
}
```

## **C. Property Walkthrough & Client Onboarding Intake SOP**

* **Recommended File Format:** `WALKTHROUGH_AND_INTAKE_SOP.md` (Markdown)  
* **Rationale:** Operational standard operating procedure for client onboarding, property hazard assessment, initial deep clean quote generation, and square footage validation.  
* **Specification Blueprint:**

```
# STANDARD OPERATING PROCEDURE: Property Walkthrough & Client Onboarding

## 1. 5-Step Property Walkthrough Intake Protocol

1. **Initial Property Audit:** Conduct a 30-minute on-site assessment with client or property manager.
2. **Surface Sensitivity Mapping:** Log all sensitive materials (honed Carrara marble, unsealed butcher block, oil-rubbed bronze hardware, wool area rugs).
3. **Pre-Existing Condition Documentation:** Photograph existing carpet stains, scratched wood floors, and chipped tiles; upload to client profile.
4. **Air Quality & Allergen Assessment:** Identify presence of pets, dust sensitivities, or fragrance allergies to tailor hypoallergenic essential oils.
5. **Estimate & Scope Confirmation:** Generate fixed-price proposal detailing initial deep-clean baseline hours and ongoing maintenance frequencies.

## 2. Mandatory Initial Deep-Clean Requirement

All recurring service contracts must undergo a foundational **Initial Deep Clean**. This baseline visit removes pre-existing buildup, limescale, and synthetic wax residues from previous chemical cleaners before beginning botanical maintenance.
```

## **D. Property Access, Key Handling & Cancellation Policy**

* **Recommended File Format:** `PROPERTY_ACCESS_AND_CANCELLATION_POLICY.md` (Markdown)  
* **Rationale:** Customer-facing legal and operational policy detailing secure lockbox codes, smart lock integration, alarm system protocols, lockout fees, and cancellation cutoff windows.  
* **Specification Blueprint:**

```
# PROPERTY ACCESS, SECURITY & CANCELLATION POLICY

## 1. Secure Access & Key Storage Protocols

* **Digital Keypads & Smart Locks:** Preferred access method. Clients provide a unique service PIN designated exclusively for Kettle & Loom staff.
* **Physical Lockboxes:** If using physical keys, keys must remain inside a secure on-site lockbox. Technicians will not carry permanent property keys off-site.
* **Alarm Systems:** Alarm disarm codes and re-arming instructions must be stored in encrypted client profiles. Any false alarm dispatch fees resulting from inaccurate client codes are the client's responsibility.

## 2. Cancellation & Rescheduling Cutoff Schedules

* **48-Hour Free Cancellation:** Services may be canceled or rescheduled without penalty up to **48 hours** prior to the scheduled arrival window.
* **Late Cancellation (Within 24–48 Hours):** Incurs a **$50.00 administrative rescheduling fee**.
* **Same-Day Cancellation / Lockout (Under 24 Hours):** Charged at **100% of the scheduled service fee**. Our collective technicians are scheduled and paid for their booked time.

## 3. Pet Safety & Containment Rules

We love pets, but for technician safety and to prevent pets from darting out exterior doors, dogs and cats must be secured in a designated room or crate during service unless prior written arrangements are confirmed.
```

## **E. Post-Construction Fine Dust Remediation Protocol**

* **Recommended File Format:** `POST_CONSTRUCTION_REMEDIATION_GUIDE.md` (Markdown)  
* **Rationale:** Heavy-duty technical cleaning guide covering crystalline silica and drywall particulate extraction, HEPA filtration, and multi-pass microfiber dusting.  
* **Specification Blueprint:**

```
# TECHNICAL GUIDE: Post-Construction Fine Dust Remediation

## 1. The Three-Phase Construction Remediation Methodology

Post-construction cleaning requires a sequential three-phase approach to capture settling airborne drywall gypsum and sawdust:

1. **Phase 1: Rough Debris Pass:** Removal of construction packaging, protective films, tape residue, and rough floor sweeping with HEPA capture.
2. **Phase 2: High-to-Low HEPA Vacuuming:** Dry particle extraction starting from ceiling joists, HVAC diffusers, door casings, down to baseboards.
3. **Phase 3: Wet Microfiber Sparkle Pass:** Multi-bucket damp wipe using electrostatic microfiber cloths to capture remaining microscopic dust films.

## 2. HEPA Air Scrubbing & Particle Trapping Standards

* **Equipment Standard:** Commercial HEPA vacuums certified to capture **99.97% of particulates down to 0.3 microns**.
* **Microfiber Fold Technique:** Microfiber cloths must be folded into 8 clean quadrants and flipped continuously to prevent spreading dry drywall dust across painted walls.
```

## **F. Master Customer Support FAQ Knowledge Base**

* **Recommended File Format:** `faq_support_knowledgebase.json` (JSON formatted with 4-space indentation)  
* **Rationale:** Structured JSON knowledge base ready for programmatic ingestion, vector database chunking, or RAG chatbot agent pipelines.  
* **Specification Blueprint:**

```json
{
    "knowledgebase_metadata": {
        "company": "Kettle & Loom Cleaning Collective",
        "system_id": "KB-KL-2024-V1",
        "total_entries": 5
    },
    "faqs": [
        {
            "id": "FAQ-ECO-001",
            "category": "Chemical Safety & Eco-Standards",
            "question": "Are your cleaning products safe for homes with infants and pets?",
            "answer": "Yes. All our products are 100% non-toxic, zero-VOC, and plant- or mineral-derived. Our primary hospital-grade disinfectant uses botanical thymol (thyme oil extract), which kills 99.99% of bacteria and viruses without leaving behind toxic chemical residues or harsh fumes.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-ACC-002",
            "category": "Property Access & Security",
            "question": "Do I need to be home when the cleaning collective arrives?",
            "answer": "No. Most residential and commercial clients provide a smart lock code or lockbox key. Our technicians arrive within the designated arrival window, complete the service scope, re-secure all windows and doors, and set the security alarm upon departure.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-CAN-003",
            "category": "Booking & Cancellations",
            "question": "What happens if I need to cancel my cleaning appointment tomorrow?",
            "answer": "Appointments canceled with less than 24 hours notice are subject to a 100% service fee charge because our collective members are paid for their booked time. If canceled between 24 and 48 hours in advance, a $50 administrative fee applies. Cancellations with over 48 hours notice are completely free.",
            "escalate_to_human": true
        },
        {
            "id": "FAQ-SCP-004",
            "category": "Scope of Services",
            "question": "Do you clean unsealed marble or antique wood furniture?",
            "answer": "During your initial walkthrough, our team maps all sensitive surfaces. We use pH-neutral saponified soap washes for hardwood and unsealed stone. We strictly prohibit the use of acidic descalers on marble, limestone, or terrazzo to prevent etching.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-PST-005",
            "category": "Post-Construction Services",
            "question": "Why does post-construction cleaning require multiple passes?",
            "answer": "Drywall and sawdust particles remain suspended in the air for up to 48 hours after construction wraps up. We utilize certified 0.3-micron HEPA vacuums and a structured three-phase process (rough pass, deep vacuum, damp microfiber sparkle wipe) to prevent settling dust from coating surfaces after cleaning.",
            "escalate_to_human": false
        }
    ]
}
```
