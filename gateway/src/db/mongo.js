const path = require("path");
const { MongoClient } = require("mongodb");
const dotenv = require("dotenv");
const { PRESET_TENANTS } = require("../config/presets");
const { resolveRuntimeConfig } = require("../config/mode");

// Load .env from project root without clobbering explicit CLI environment variables
const rootEnvPath = path.resolve(__dirname, "../../../.env");
dotenv.config({ path: rootEnvPath, override: false });
dotenv.config({ override: false });

const DEFAULT_TENANTS = PRESET_TENANTS;

const DEFAULT_TICKETS = [
    // Iron & Oak Provision Co.
    {
        ticket_id: "TKT-IO-1041",
        tenant_id: "iron_and_oak",
        customer_contact: {
            name: "Marcus Vance",
            email: "m.vance@deserttrail.org",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "How often should I condition my vegetable-tanned leather boots if I live in Arizona where humidity is under 25%?",
        answer:
            "In dry climates with relative humidity under 30%, you should condition your vegetable-tanned leather every 3 to 4 months using a dime-sized amount of natural beeswax or neatsfoot oil balm. Let the balm absorb for 12 hours before buffing off any excess.",
        messages: [
            {
                role: "customer",
                content:
                    "Hi there, I just picked up a pair of your vegetable-tanned leather field boots.",
                timestamp: "2026-10-29T14:10:12.000Z",
            },
            {
                role: "agent",
                content:
                    "Welcome to Iron & Oak. For standard climates, we recommend conditioning vegetable-tanned leather every 6 months with natural beeswax or neatsfoot oil balm.",
                timestamp: "2026-10-29T14:10:15.000Z",
            },
            {
                role: "customer",
                content:
                    "How often should I condition my vegetable-tanned leather boots if I live in Arizona where humidity is under 25%?",
                timestamp: "2026-10-29T14:12:00.000Z",
            },
            {
                role: "agent",
                content:
                    "In dry climates with relative humidity under 30%, you should condition your vegetable-tanned leather every 3 to 4 months using a dime-sized amount of natural beeswax or neatsfoot oil balm. Let the balm absorb for 12 hours before buffing off any excess.",
                timestamp: "2026-10-29T14:12:03.000Z",
            },
        ],
        rationale:
            "According to [CARE_GUIDE#1. Vegetable-Tanned Leather Maintenance], standard conditioning is every 6 months, but dry climates (under 30% relative humidity) require conditioning every 3 to 4 months with a dime-sized amount of beeswax or neatsfoot oil balm absorbed for 12 hours.",
        similarity_score: 0.89,
        retrieved_chunks: [
            {
                doc_id: "CARE_GUIDE",
                section: "1. Vegetable-Tanned Leather Maintenance",
                score: 0.89,
                text: "- **Biannual Conditioning:** Apply natural beeswax or neatsfoot oil balm every **6 months** to prevent dry cracking. - Dry climates (under 30% relative humidity): condition every **3 to 4 months**. - **How to Condition:** 1. Brush off dirt and dust. 2. Wipe with a damp cloth and let it dry for 1 hour at room temperature. 3. Work a **dime-sized amount** of balm in with a clean cloth, using small circles. 4. Let it absorb for 12 hours, then buff off the excess.",
            },
            {
                doc_id: "CARE_GUIDE",
                section: "LEATHER & WAXED CANVAS CARE GUIDE",
                score: 0.76,
                text: "**Iron & Oak Provision Co.** — *Built for the Trail. Proven for a Lifetime.* Good gear lasts if you treat it right. None of this takes long.",
            },
        ],
        status: "resolved",
        admin_notes: "Verified against CARE_GUIDE section 1.",
        admin_reply: null,
        created_at: "2026-10-29T14:12:00.000Z",
    },
    {
        ticket_id: "TKT-IO-1042",
        tenant_id: "iron_and_oak",
        customer_contact: {
            name: "Elena Rostova",
            email: "elena.rostova@pnwmail.io",
        },
        escalation_reason: "none",
        ticket_summary:
            "Customer has a Medium Timberline Waxed Chore Coat (45-inch chest) and asked if she should exchange for a Large when layering over a heavy wool sweater.",
        question:
            "I bought a Timberline Waxed Chore Coat in size Medium, and I want to wear it over a heavy wool sweater. Will the chest measurement fit or should I exchange it?",
        answer:
            "The Timberline Waxed Chore Coat uses our Field Fit profile (45-inch chest in size Medium), which is designed to fit over a thermal base layer and a midweight knit. If you are between sizes or layering over a heavy sweater, our sizing guide recommends sizing up to a Large (48-inch chest).",
        messages: [
            {
                role: "customer",
                content:
                    "What are the exact chest and sleeve dimensions on the Timberline Waxed Chore Coat in Medium?",
                timestamp: "2026-10-30T09:43:10.000Z",
            },
            {
                role: "agent",
                content:
                    "In size Medium (SKU APP-CC-001-M), the Timberline Waxed Chore Coat measures 45 inches across the chest, 35.5 inches in sleeve length, 19.5 inches across the shoulder, and 30 inches in back length.",
                timestamp: "2026-10-30T09:43:14.000Z",
            },
            {
                role: "customer",
                content:
                    "I bought a Timberline Waxed Chore Coat in size Medium, and I want to wear it over a heavy wool sweater. Will the chest measurement fit or should I exchange it?",
                timestamp: "2026-10-30T09:45:00.000Z",
            },
            {
                role: "agent",
                content:
                    "The Timberline Waxed Chore Coat uses our Field Fit profile (45-inch chest in size Medium), which is designed to fit over a thermal base layer and a midweight knit. If you are between sizes or layering over a heavy sweater, our sizing guide recommends sizing up to a Large (48-inch chest).",
                timestamp: "2026-10-30T09:45:03.000Z",
            },
        ],
        rationale:
            "Chunk [sizing_specs#products - Timberline Waxed Chore Coat] specifies size M has a 45-inch chest with Field Fit and notes 'Between sizes: size up if layering over a midweight knit.' Chunk [sizing_specs#fit_definitions] confirms Field Fit accommodates up to a thermal base layer and midweight knit (2 inches total ease).",
        similarity_score: 0.73,
        retrieved_chunks: [
            {
                doc_id: "sizing_specs",
                section: "products - Timberline Waxed Chore Coat",
                score: 0.73,
                text: "{\"sku\": \"APP-CC-001\", \"name\": \"Timberline Waxed Chore Coat\", \"fit_profile\": \"Field Fit (relaxed through shoulders and chest)\", \"size_matrix\": {\"M\": {\"chest\": 45, \"sleeve\": 35.5, \"shoulder\": 19.5, \"length\": 30}, \"L\": {\"chest\": 48, \"sleeve\": 36.5, \"shoulder\": 20.5, \"length\": 30.5}}, \"sizing_advice\": \"Between sizes: size up if layering over a midweight knit.\"}",
            },
            {
                doc_id: "sizing_specs",
                section: "fit_definitions",
                score: 0.71,
                text: "fit_definitions: {\"field_fit\": {\"description\": \"Relaxed through shoulders and chest with room for movement and layering.\", \"layering_allowance\": \"Fits over a thermal base layer and a midweight knit (up to approximately 1 inch of garment ease per layer, 2 inches total)\"}}",
            },
        ],
        status: "pending_review",
        admin_notes: "",
        created_at: "2026-10-30T09:45:00.000Z",
    },
    {
        ticket_id: "TKT-IO-1043",
        tenant_id: "iron_and_oak",
        customer_contact: {
            name: "Devon Brooks",
            email: "dbrooks@gmail.com",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "Can I throw my waxed canvas field bag in the washing machine on gentle cold if I use castile soap?",
        answer:
            "No. Never machine wash, dry clean, or tumble dry waxed canvas, and do not use soap, detergent, or solvents, as they strip the wax finish. Brush off dry dirt with a soft brush and spot clean with cold water only, then hang to air dry away from direct heat.",
        messages: [
            {
                role: "customer",
                content:
                    "Can I throw my waxed canvas field bag in the washing machine on gentle cold if I use castile soap?",
                timestamp: "2026-10-30T16:20:00.000Z",
            },
            {
                role: "agent",
                content:
                    "No. Never machine wash, dry clean, or tumble dry waxed canvas, and do not use soap, detergent, or solvents, as they strip the wax finish. Brush off dry dirt with a soft brush and spot clean with cold water only, then hang to air dry away from direct heat.",
                timestamp: "2026-10-30T16:20:02.000Z",
            },
        ],
        rationale:
            "In [CARE_GUIDE#Routine Cleaning], policy explicitly prohibits machine washing, dry cleaning, tumble drying, and using any soap or detergent on waxed canvas because it strips the wax.",
        similarity_score: 0.86,
        retrieved_chunks: [
            {
                doc_id: "CARE_GUIDE",
                section: "Routine Cleaning",
                score: 0.86,
                text: "- Brush off dry mud and dust with a soft brush. - Spot clean with **cold water** and a soft brush or sponge. Do not use soap, detergent, or solvents, because they strip the wax. - Hang to air dry, away from direct heat. - **Never** machine wash, dry clean, or tumble dry.",
            },
        ],
        status: "resolved",
        admin_notes: "",
        created_at: "2026-10-30T16:20:00.000Z",
    },
    {
        ticket_id: "TKT-IO-1044",
        tenant_id: "iron_and_oak",
        customer_contact: {
            name: "Hannah Lin (Summit Partners)",
            email: "hlin@summitpartners.co",
        },
        escalation_reason: "not_in_docs",
        ticket_summary:
            "Corporate buyer Hannah Lin inquired about wholesale pricing for 30 heritage duffels and then asked for custom monogram embossing and production lead times. Monogramming is not covered in WHOLESALE_SOP.md; escalated for B2B human follow-up.",
        question:
            "Do you offer custom monogram embossing on corporate orders of 30 heritage duffels, and what is the lead time?",
        answer:
            "I cannot confirm whether custom monogram embossing is offered on corporate orders, as monogramming services are not listed in our wholesale documentation. I have logged your contact details so our Wholesale & B2B team can follow up with you directly regarding custom branding options and lead times.",
        messages: [
            {
                role: "customer",
                content:
                    "We are looking to place a corporate gift order of 30 leather-trimmed heritage duffels for our annual retreat.",
                timestamp: "2026-10-31T11:02:18.000Z",
            },
            {
                role: "agent",
                content:
                    "We support bulk and corporate orders through our Wholesale & B2B program. Do you have specific customization or delivery date requirements?",
                timestamp: "2026-10-31T11:02:22.000Z",
            },
            {
                role: "customer",
                content:
                    "Do you offer custom monogram embossing on corporate orders of 30 heritage duffels, and what is the lead time?",
                timestamp: "2026-10-31T11:05:00.000Z",
            },
            {
                role: "agent",
                content:
                    "I cannot confirm whether custom monogram embossing is offered on corporate orders, as monogramming services are not listed in our wholesale documentation. I have logged your contact details so our Wholesale & B2B team can follow up with you directly regarding custom branding options and lead times.",
                timestamp: "2026-10-31T11:05:04.000Z",
            },
        ],
        rationale:
            "Retrieved chunks from [WHOLESALE_SOP] and [faq_support_knowledgebase] had low similarity (0.61) and do not mention monogramming or custom embossing services; escalated per unanswerable policy.",
        similarity_score: 0.61,
        retrieved_chunks: [
            {
                doc_id: "WHOLESALE_SOP",
                section: "Overview",
                score: 0.61,
                text: "Wholesale accounts require a valid resale certificate and minimum opening order quantity.",
            },
        ],
        status: "flagged",
        admin_notes:
            "Consider adding custom branding / corporate gifting FAQ entry to WHOLESALE_SOP.md.",
        created_at: "2026-10-31T11:05:00.000Z",
    },

    // Cinder & Salt Bakery
    {
        ticket_id: "TKT-CS-2011",
        tenant_id: "cinder_and_salt",
        customer_contact: {
            name: "Claire Alvarez",
            email: "claire.alvarez@familyhealth.net",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "My daughter has celiac disease. Since your sourdough undergoes a 36-hour cold fermentation, is your flourless buckwheat loaf safe for her?",
        answer:
            "No, our products are not safe for customers with Celiac Disease. Because we operate an open-concept bakery and active stone mill, flour particles remain airborne 24 hours a day. In addition, 24–36 hour cold fermentation does not reduce gluten below the 20 ppm celiac-safe threshold.",
        messages: [
            {
                role: "customer",
                content:
                    "My daughter has celiac disease. Since your sourdough undergoes a 36-hour cold fermentation, is your flourless buckwheat loaf safe for her?",
                timestamp: "2026-10-30T08:15:00.000Z",
            },
            {
                role: "agent",
                content:
                    "No, our products are not safe for customers with Celiac Disease. Because we operate an open-concept bakery and active stone mill, flour particles remain airborne 24 hours a day. In addition, 24–36 hour cold fermentation does not reduce gluten below the 20 ppm celiac-safe threshold.",
                timestamp: "2026-10-30T08:15:03.000Z",
            },
        ],
        rationale:
            "Direct citation from [ALLERGEN_SAFETY_PROTOCOL#1. Airborne Flour & Celiac Safety Notice] states the facility is NOT celiac-safe due to 24/7 airborne flour from the stone mill and explicitly notes cold fermentation does not reduce gluten to <20 ppm.",
        similarity_score: 0.92,
        retrieved_chunks: [
            {
                doc_id: "ALLERGEN_SAFETY_PROTOCOL",
                section: "1. Airborne Flour & Celiac Safety Notice",
                score: 0.92,
                text: "- **Gluten Presence:** Fine flour particles remain airborne throughout the facility 24 hours a day. - **Celiac Disclaimer:** While some items are prepared without gluten-containing ingredients, **our facility is NOT celiac-safe**. Customers with Celiac Disease, severe gluten intolerance, or wheat allergy should not consume our products. - **Fermentation Is Not a Safety Claim:** Our 24–36 hour cold fermentation does **not** reduce gluten to a celiac-safe level (the regulatory threshold is under 20 ppm).",
            },
        ],
        status: "resolved",
        admin_notes: "",
        created_at: "2026-10-30T08:15:00.000Z",
    },
    {
        ticket_id: "TKT-CS-2012",
        tenant_id: "cinder_and_salt",
        customer_contact: {
            name: "Noah Sterling",
            email: "noah.sterling@bistrogroup.com",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "How do you store tree nuts in the kitchen to prevent cross-contact with nut-free pastries?",
        answer:
            "Tree nuts (walnuts and almonds) are stored in sealed lug containers on the top shelf of dry storage and handled using dedicated red color-coded equipment.",
        messages: [
            {
                role: "customer",
                content:
                    "Do you use walnuts or almonds in your morning pastry bakes?",
                timestamp: "2026-10-31T10:28:00.000Z",
            },
            {
                role: "agent",
                content:
                    "Yes, both walnuts and almonds are present in our facility and used in select pastries.",
                timestamp: "2026-10-31T10:28:03.000Z",
            },
            {
                role: "customer",
                content:
                    "How do you store tree nuts in the kitchen to prevent cross-contact with nut-free pastries?",
                timestamp: "2026-10-31T10:30:00.000Z",
            },
            {
                role: "agent",
                content:
                    "Tree nuts (walnuts and almonds) are stored in sealed lug containers on the top shelf of dry storage and handled using dedicated red color-coded equipment.",
                timestamp: "2026-10-31T10:30:02.000Z",
            },
        ],
        rationale:
            "Verified in [ALLERGEN_SAFETY_PROTOCOL#2. Allergen Matrix & Kitchen Separation], which specifies Tree Nuts use Dedicated Equipment (Color-coded Red) and Sealed lug containers on the top shelf of dry storage.",
        similarity_score: 0.74,
        retrieved_chunks: [
            {
                doc_id: "ALLERGEN_SAFETY_PROTOCOL",
                section: "2. Allergen Matrix & Kitchen Separation",
                score: 0.74,
                text: "| **Tree Nuts** | Yes (Walnuts, Almonds) | Yes (Color-coded Red) | Sealed lug containers, top shelf of dry storage |",
            },
        ],
        status: "pending_review",
        admin_notes: "Check if top-shelf vs bottom-shelf storage note needs review.",
        created_at: "2026-10-31T10:30:00.000Z",
    },

    // Harbor View Veterinary Clinic
    {
        ticket_id: "TKT-HV-3001",
        tenant_id: "harbor_view",
        customer_contact: {
            name: "Samira Patel",
            email: "spatel@seattlemail.com",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "Can I take my dog's E-collar off for 15 minutes while I watch him eat dinner on day 4 after surgery?",
        answer:
            "Keep the Elizabethan collar (E-collar) securely fastened 24/7 for 10 to 14 days unless your discharge instructions specifically direct otherwise. Even 30 seconds of licking can pull out sutures and introduce oral bacteria into the incision.",
        messages: [
            {
                role: "customer",
                content:
                    "Can I take my dog's E-collar off for 15 minutes while I watch him eat dinner on day 4 after surgery?",
                timestamp: "2026-10-30T13:10:00.000Z",
            },
            {
                role: "agent",
                content:
                    "Keep the Elizabethan collar (E-collar) securely fastened 24/7 for 10 to 14 days unless your discharge instructions specifically direct otherwise. Even 30 seconds of licking can pull out sutures and introduce oral bacteria into the incision.",
                timestamp: "2026-10-30T13:10:03.000Z",
            },
        ],
        rationale:
            "Grounded in [POST_OP_CARE_GUIDE#1. Incision Site Monitoring & Protection], which requires 24/7 E-collar compliance for 10 to 14 days because even 30 seconds of licking can dehisce sutures.",
        similarity_score: 0.91,
        retrieved_chunks: [
            {
                doc_id: "POST_OP_CARE_GUIDE",
                section: "1. Incision Site Monitoring & Protection",
                score: 0.91,
                text: "- **Elizabethan Collar (E-Collar) Compliance:** The E-collar must remain securely fastened **24/7 for 10 to 14 days**. Even 30 seconds of licking can pull out sutures and introduce oral bacteria.",
            },
        ],
        status: "resolved",
        admin_notes: "",
        created_at: "2026-10-30T13:10:00.000Z",
    },
    {
        ticket_id: "TKT-HV-3002",
        tenant_id: "harbor_view",
        customer_contact: {
            name: "Jordan Mercer",
            email: "jmercer@harborclient.org",
        },
        escalation_reason: "docs_require_human",
        ticket_summary:
            "Client reported cat's rectal temperature is 103.6°F 48 hours post-spay and asked about waiting until morning. Advised immediate urgent triage and flagged for veterinary nurse follow-up.",
        question:
            "My cat's rectal temperature is 103.6°F two days after her spay surgery. Should I wait until morning?",
        answer:
            "No, please contact our clinic immediately for urgent triage. Normal rectal temperature for cats and dogs is 100.5°F–102.5°F, and a post-operative temperature above 103.0°F is a systemic warning sign that requires immediate veterinary evaluation.",
        messages: [
            {
                role: "customer",
                content:
                    "My cat had her spay surgery two days ago and seems very lethargic tonight.",
                timestamp: "2026-10-31T17:43:10.000Z",
            },
            {
                role: "agent",
                content:
                    "Post-operative lethargy after 48 hours should be monitored closely. Have you been able to check her gum color or rectal temperature?",
                timestamp: "2026-10-31T17:43:14.000Z",
            },
            {
                role: "customer",
                content:
                    "My cat's rectal temperature is 103.6°F two days after her spay surgery. Should I wait until morning?",
                timestamp: "2026-10-31T17:45:00.000Z",
            },
            {
                role: "agent",
                content:
                    "No, please contact our clinic immediately for urgent triage. Normal rectal temperature for cats and dogs is 100.5°F–102.5°F, and a post-operative temperature above 103.0°F is a systemic warning sign that requires immediate veterinary evaluation.",
                timestamp: "2026-10-31T17:45:03.000Z",
            },
        ],
        rationale:
            "According to [POST_OP_CARE_GUIDE#2. Temperature & Systemic Warning Signs], normal temperature is 100.5°F–102.5°F and post-op fever requires urgent clinical triage.",
        similarity_score: 0.68,
        retrieved_chunks: [
            {
                doc_id: "POST_OP_CARE_GUIDE",
                section: "2. Temperature & Systemic Warning Signs",
                score: 0.68,
                text: "Normal rectal temperature for dogs and cats is **100.5°F–102.5°F (38.1°C–39.2°C)**.",
            },
        ],
        status: "flagged",
        admin_notes:
            "Escalated post-op fever case; verify triage phone number is prominent.",
        created_at: "2026-10-31T17:45:00.000Z",
    },

    // Kettle & Loom Cleaning Collective
    {
        ticket_id: "TKT-KL-4001",
        tenant_id: "kettle_and_loom",
        customer_contact: {
            name: "Liam O'Connor",
            email: "loconnor@buildcraft.io",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "Our drywall contractors finish sanding on Tuesday at 5 PM. Can your team do the final post-construction clean on Wednesday morning at 8 AM?",
        answer:
            "For the final remediation pass, we recommend waiting at least 24 to 48 hours after the last drywall sanding or cutting so airborne gypsum dust can fully settle. We typically schedule Phase 2 (High-to-Low HEPA vacuuming) and Phase 3 (Wet Microfiber wipe) as separate visits after the settling window.",
        messages: [
            {
                role: "customer",
                content:
                    "Our drywall contractors finish sanding on Tuesday at 5 PM. Can your team do the final post-construction clean on Wednesday morning at 8 AM?",
                timestamp: "2026-10-30T15:00:00.000Z",
            },
            {
                role: "agent",
                content:
                    "For the final remediation pass, we recommend waiting at least 24 to 48 hours after the last drywall sanding or cutting so airborne gypsum dust can fully settle. We typically schedule Phase 2 (High-to-Low HEPA vacuuming) and Phase 3 (Wet Microfiber wipe) as separate visits after the settling window.",
                timestamp: "2026-10-30T15:00:03.000Z",
            },
        ],
        rationale:
            "Cited from [POST_CONSTRUCTION_REMEDIATION_GUIDE#Phase Details]: 'Allow dust to settle for at least 24 to 48 hours after the last drywall sanding or cutting before the final pass. We usually schedule Phase 2 and Phase 3 as separate visits.'",
        similarity_score: 0.87,
        retrieved_chunks: [
            {
                doc_id: "POST_CONSTRUCTION_REMEDIATION_GUIDE",
                section: "Phase Details",
                score: 0.87,
                text: "- Work **high to low** and **back to front**, and finish at the entrance. - Allow dust to settle for at least **24 to 48 hours** after the last drywall sanding or cutting before the final pass. We usually schedule Phase 2 and Phase 3 as separate visits.",
            },
        ],
        status: "resolved",
        admin_notes: "",
        created_at: "2026-10-30T15:00:00.000Z",
    },
    {
        ticket_id: "TKT-KL-4002",
        tenant_id: "kettle_and_loom",
        customer_contact: {
            name: "Maya Lin",
            email: "maya@linarchitects.com",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "What micron rating do your HEPA vacuums trap during drywall dust remediation?",
        answer:
            "We use commercial HEPA vacuums certified to capture 99.97% of particulates down to 0.3 microns, alongside a 8-quadrant damp microfiber folding protocol.",
        messages: [
            {
                role: "customer",
                content:
                    "What micron rating do your HEPA vacuums trap during drywall dust remediation?",
                timestamp: "2026-10-31T12:20:00.000Z",
            },
            {
                role: "agent",
                content:
                    "We use commercial HEPA vacuums certified to capture 99.97% of particulates down to 0.3 microns, alongside a 8-quadrant damp microfiber folding protocol.",
                timestamp: "2026-10-31T12:20:03.000Z",
            },
        ],
        rationale:
            "Directly stated in [POST_CONSTRUCTION_REMEDIATION_GUIDE#2. HEPA Air Scrubbing & Particle Trapping Standards]: commercial HEPA vacuums are certified to capture 99.97% of particulates down to 0.3 microns.",
        similarity_score: 0.72,
        retrieved_chunks: [
            {
                doc_id: "POST_CONSTRUCTION_REMEDIATION_GUIDE",
                section: "2. HEPA Air Scrubbing & Particle Trapping Standards",
                score: 0.72,
                text: "* **Equipment Standard:** Commercial HEPA vacuums certified to capture **99.97% of particulates down to 0.3 microns**. Certification labels must be on the machine, and filters are inspected before every project.",
            },
        ],
        status: "pending_review",
        admin_notes: "",
        created_at: "2026-10-31T12:20:00.000Z",
    },

    // NorthStar Auto Care
    {
        ticket_id: "TKT-NSA-5001",
        tenant_id: "northstar_auto",
        customer_contact: {
            name: "Carlos Mendez",
            email: "cmendez@northstarfleet.com",
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "How much do you charge to diagnose a check engine light, and does that fee go toward the repair if I fix it at your shop?",
        answer:
            "Our comprehensive check engine light diagnostic fee is $145.00, which covers an OBD-II telemetry scan, circuit testing, and up to one hour of mechanical triage. If you approve the recommended repair with us, 100% of the $145.00 diagnostic fee is credited toward your repair labor.",
        messages: [
            {
                role: "customer",
                content:
                    "How much do you charge to diagnose a check engine light, and does that fee go toward the repair if I fix it at your shop?",
                timestamp: "2026-10-29T18:00:00.000Z",
            },
            {
                role: "agent",
                content:
                    "Our comprehensive check engine light diagnostic fee is $145.00, which covers an OBD-II telemetry scan, circuit testing, and up to one hour of mechanical triage. If you approve the recommended repair with us, 100% of the $145.00 diagnostic fee is credited toward your repair labor.",
                timestamp: "2026-10-29T18:00:02.000Z",
            },
        ],
        rationale:
            "Verified in [faq_support_knowledgebase#faqs - FAQ-DIAG-001]: diagnostic fee is $145.00 and 100% of the fee is credited directly toward repair labor upon approval.",
        similarity_score: 0.94,
        retrieved_chunks: [
            {
                doc_id: "faq_support_knowledgebase",
                section: "faqs - FAQ-DIAG-001",
                score: 0.94,
                text: "{\"id\": \"FAQ-DIAG-001\", \"category\": \"Diagnostics & Estimates\", \"question\": \"How much does a check engine light diagnosis cost?\", \"answer\": \"Our comprehensive diagnostic fee is $145.00, which includes computerized OBD-II telemetry scan, circuit testing, and up to one hour of hands-on mechanical triage. If you approve the recommended repair with us, 100% of the $145.00 diagnostic fee is credited directly toward your repair labor.\"}",
            },
        ],
        status: "resolved",
        admin_notes: "",
        created_at: "2026-10-29T18:00:00.000Z",
    },
    {
        ticket_id: "TKT-NSA-5002",
        tenant_id: "northstar_auto",
        customer_contact: {
            name: "Rachel Kim",
            email: "rkim@ TwinCitiesMail.com".replace(/\s+/g, "").toLowerCase(),
        },
        escalation_reason: "none",
        ticket_summary: "",
        question:
            "My digital inspection report shows YELLOW on my rear brake pads at 4.5 mm. Do I need to replace them today?",
        answer:
            "A YELLOW rating indicates moderate wear (such as brake pads measuring 4 to 5 mm), meaning they do not require immediate replacement today but should be monitored before your next service interval. A RED rating (below 2 mm) indicates an immediate safety risk requiring prompt repair.",
        messages: [
            {
                role: "customer",
                content:
                    "I just received the SMS link to my 40-point inspection report.",
                timestamp: "2026-10-31T14:38:12.000Z",
            },
            {
                role: "agent",
                content:
                    "I can help explain any of the inspection items or ratings on your report. Which item are you looking at?",
                timestamp: "2026-10-31T14:38:15.000Z",
            },
            {
                role: "customer",
                content:
                    "My digital inspection report shows YELLOW on my rear brake pads at 4.5 mm. Do I need to replace them today?",
                timestamp: "2026-10-31T14:40:00.000Z",
            },
            {
                role: "agent",
                content:
                    "A YELLOW rating indicates moderate wear (such as brake pads measuring 4 to 5 mm), meaning they do not require immediate replacement today but should be monitored before your next service interval. A RED rating (below 2 mm) indicates an immediate safety risk requiring prompt repair.",
                timestamp: "2026-10-31T14:40:03.000Z",
            },
        ],
        rationale:
            "Grounded in [faq_support_knowledgebase#faqs - FAQ-DIAG-002], which defines GREEN as within spec, YELLOW as moderate wear (4 to 5 mm brake pads) to monitor before next service, and RED as <2 mm needing prompt repair.",
        similarity_score: 0.71,
        retrieved_chunks: [
            {
                doc_id: "faq_support_knowledgebase",
                section: "faqs - FAQ-DIAG-002",
                score: 0.71,
                text: "{\"id\": \"FAQ-DIAG-002\", \"category\": \"Diagnostics & Estimates\", \"question\": \"What do the Green, Yellow, and Red ratings on my inspection mean?\", \"answer\": \"Every vehicle gets a 40-point digital inspection with photos. GREEN means the part is within specification. YELLOW means moderate wear, such as brake pads at 4 to 5 mm, so keep an eye on it before your next service. RED means a safety or drivability risk, such as brake pads below 2 mm, a torn CV boot, or a pressurized coolant leak, and needs prompt repair.\"}",
            },
        ],
        status: "pending_review",
        admin_notes: "",
        created_at: "2026-10-31T14:40:00.000Z",
    },
];

let clientInstance = null;
let dbInstance = null;
let connectedDbName = null;
let customDbAdapter = null;

async function ensureIndexes(db) {
    const businesses = db.collection("businesses");
    await businesses.createIndex({ tenant_id: 1 }, { unique: true });

    const ticketLogs = db.collection("ticket_logs");
    await ticketLogs.createIndex({ ticket_id: 1 }, { unique: true });
    await ticketLogs.createIndex({ tenant_id: 1, status: 1, created_at: -1 });

    const adminUsers = db.collection("admin_users");
    await adminUsers.createIndex({ email: 1 }, { unique: true });
    await adminUsers.createIndex({ user_id: 1 }, { unique: true });
    await adminUsers.createIndex({ tenant_id: 1 });

    const adminSessions = db.collection("admin_sessions");
    await adminSessions.createIndex({ session_id_hash: 1 }, { unique: true });
    await adminSessions.createIndex({ expires_at: 1 });
}

async function seedPresetTrainingData(db) {
    const businesses = db.collection("businesses");
    const ticketLogs = db.collection("ticket_logs");
    const nowIso = new Date().toISOString();

    for (const tenant of DEFAULT_TENANTS) {
        await businesses.updateOne(
            { tenant_id: tenant.tenant_id },
            {
                $setOnInsert: {
                    ...tenant,
                    updated_at: nowIso,
                },
            },
            { upsert: true }
        );
    }

    for (const ticket of DEFAULT_TICKETS) {
        await ticketLogs.updateOne(
            { ticket_id: ticket.ticket_id },
            {
                $setOnInsert: {
                    ...ticket,
                    updated_at: nowIso,
                },
            },
            { upsert: true }
        );

        await ticketLogs.updateOne(
            {
                ticket_id: ticket.ticket_id,
                messages: { $exists: false },
            },
            {
                $set: {
                    customer_contact: ticket.customer_contact,
                    escalation_reason: ticket.escalation_reason,
                    ticket_summary: ticket.ticket_summary,
                    messages: ticket.messages,
                },
            }
        );
    }
}

async function initializeDatabaseForMode(db, appMode) {
    await ensureIndexes(db);
    if (appMode === "preset_training") {
        await seedPresetTrainingData(db);
    }
}

function setDatabaseAdapter(adapter) {
    customDbAdapter = adapter;
}

function resetDatabaseAdapter() {
    customDbAdapter = null;
}

async function connectToDatabase(env = process.env) {
    const runtimeConfig = resolveRuntimeConfig(env);
    const { appMode, activeDbName } = runtimeConfig;

    if (customDbAdapter) {
        const db =
            typeof customDbAdapter.getDbForName === "function"
                ? customDbAdapter.getDbForName(activeDbName)
                : customDbAdapter;
        await initializeDatabaseForMode(db, appMode);
        return { client: null, db, runtimeConfig };
    }

    if (dbInstance && clientInstance && connectedDbName === activeDbName) {
        return { client: clientInstance, db: dbInstance, runtimeConfig };
    }

    const mongoUri = env.MONGODB_URI;
    if (
        !mongoUri ||
        mongoUri.includes("<username>") ||
        mongoUri.includes("<password>")
    ) {
        throw new Error(
            "MONGODB_URI is missing or contains placeholder values. Check your root .env file (see .env.example)."
        );
    }

    if (!clientInstance) {
        clientInstance = new MongoClient(mongoUri, {
            serverSelectionTimeoutMS: 8000,
            connectTimeoutMS: 8000,
        });
        await clientInstance.connect();
    }

    dbInstance = clientInstance.db(activeDbName);
    connectedDbName = activeDbName;

    await initializeDatabaseForMode(dbInstance, appMode);

    return { client: clientInstance, db: dbInstance, runtimeConfig };
}

async function getDb() {
    const { activeDbName } = resolveRuntimeConfig(process.env);
    if (customDbAdapter) {
        return typeof customDbAdapter.getDbForName === "function"
            ? customDbAdapter.getDbForName(activeDbName)
            : customDbAdapter;
    }
    if (!dbInstance || connectedDbName !== activeDbName) {
        await connectToDatabase(process.env);
    }
    return dbInstance;
}

async function getBusinessesCollection() {
    const db = await getDb();
    return db.collection("businesses");
}

async function getDocVectorsCollection() {
    const db = await getDb();
    const collectionName = process.env.MONGODB_COLLECTION_NAME || "doc_vectors";
    return db.collection(collectionName);
}

async function getTicketLogsCollection() {
    const db = await getDb();
    return db.collection("ticket_logs");
}

async function getAdminUsersCollection() {
    const db = await getDb();
    return db.collection("admin_users");
}

async function getAdminSessionsCollection() {
    const db = await getDb();
    return db.collection("admin_sessions");
}

async function closeDatabase() {
    if (clientInstance) {
        await clientInstance.close();
        clientInstance = null;
        dbInstance = null;
        connectedDbName = null;
    }
}

module.exports = {
    DEFAULT_TENANTS,
    DEFAULT_TICKETS,
    connectToDatabase,
    initializeDatabaseForMode,
    getDb,
    getBusinessesCollection,
    getDocVectorsCollection,
    getTicketLogsCollection,
    getAdminUsersCollection,
    getAdminSessionsCollection,
    closeDatabase,
    setDatabaseAdapter,
    resetDatabaseAdapter,
};

