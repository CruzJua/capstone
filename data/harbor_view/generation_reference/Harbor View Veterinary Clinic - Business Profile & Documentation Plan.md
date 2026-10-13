# **Harbor View Veterinary Clinic — Business Profile & Knowledge Base Architecture**

# **1\. Brand Identity & Marketing Profile**

| Attribute | Specification |
| :---- | :---- |
| **Company Name** | Harbor View Veterinary Clinic |
| **Tagline / Slogan** | Compassionate Medicine. Modern Care. Lifelong Companionship. |
| **Industry** | Veterinary Medicine, Small-Animal Primary Care & Urgent Triage |
| **Target Demographic** | Dog and cat owners, multi-pet households, new puppy/kitten adopters, and senior pet caregivers (Ages 20–70). |
| **Core Values** | Fear-Free Handling, Transparent Treatment Plans, Preventative Wellness Focus |

## **Mission Statement**

Harbor View Veterinary Clinic provides compassionate, evidence-based medical care for companion animals through progressive wellness diagnostics, outpatient urgent triage, and comprehensive post-operative recovery support. We treat each patient with gentle, fear-free handling while providing pet guardians with transparent medical guidance, clear financial estimates, and continuous education.

## **Brand Story & Core Pillars**

* **Fear-Free Certified Patient Care:** We minimize veterinary anxiety through low-stress handling protocols, separate canine and feline reception/exam suites, species-specific synthetic pheromone diffusers (Feliway/Adaptil), and gentle restraint techniques.  
* **Transparent Treatment Estimates & Collaborative Decision-Making:** No medical surprises. Before executing diagnostic workups or surgical procedures, clients receive itemized treatment plans outlining medical recommendations, diagnostic value, and exact fee schedules.  
* **Continuous Post-Operative & Preventive Stewardship:** Patient care extends beyond our exam rooms. From structured multimodal pain management schedules to digital recovery check-ins, we guide guardians through every phase of healing.

## **Tone & Voice Guidelines**

* **Empathetic & Reassuring:** Warm, compassionate, and attentive to pet guardian anxiety during medical challenges.  
* **Clinically Precise & Accessible:** Accurate veterinary pharmacology and pathology explained in plain, understandable terms without medical gatekeeping.  
* **Ethical & Direct:** Honest and prompt regarding urgent triage prioritization, realistic prognostic timelines, and emergency hospital escalation thresholds.

---

# **2\. Documentation & Knowledge Base Breakdown**

## **A. Post-Operative Recovery & Wound Care Guide**

* **Recommended File Format**: `POST_OP_CARE_GUIDE.md` (Markdown)  
* **Rationale**: Structural discharge documentation for pet guardians following outpatient surgery (spay/neuter, soft tissue mass excision, dental extractions).  
* **Specification Blueprint**:

```
# POST-OPERATIVE CARE & HOME RECOVERY GUIDE

## 1. Incision Site Monitoring & Protection
- **Elizabethan Collar (E-Collar) Compliance:** The E-collar must remain securely fastened **24/7 for 10 to 14 days**. Even 30 seconds of licking can introduce oral bacteria or cause suture dehiscence.
- **Incision Evaluation Checklist:** Inspect the surgical site twice daily under good lighting.
  - *Normal Healing:* Mild redness, slight firm swelling along suture line, clean margins.
  - *Abnormal Symptoms (Call Clinic Immediately):* Active dripping of fresh blood, thick yellow/green discharge, foul odor, gap in tissue margins, or extreme heat.
- **Bathing Prohibition:** *No bathing, swimming, or outdoor moisture exposure for 14 days.* Moisture wicks bacteria directly into sub-dermal suture tracks.

## 2. Post-Surgical Activity Restriction
- Strict confinement to a small, carpeted room or crate without stairs, couches, or jumping obstacles.
- Dogs must be taken outdoors strictly on a **short 6-foot leash** for elimination only. No running, roughhousing, or dog park visits for 14 days.

## 3. Multimodal Pain Medication Schedule
Administer prescribed medications strictly with food to avoid gastric ulceration:
- **Carprofen (NSAID):** 2.2 mg/kg orally every 12 hours. *Do not combine with human pain relievers (Aspirin, Tylenol, or Ibuprofen are lethal to pets).*
- **Gabapentin (Neuropathic / Sedative):** 10 mg/kg orally every 8–12 hours for mild sedation and nerve pain.
```

* **Rationale**: Structural discharge documentation for pet guardians following outpatient surgery (spay/neuter, soft tissue mass excision, dental extractions).

## **B. Prescription Refill & Pharmacy Dispensing SOP**

* **Recommended File Format**: `PHARMACY_AND_REFILL_SOP.md` (Markdown)  
* **Rationale**: Operational standard operating procedure governing veterinary-client-patient relationship (VCPR) compliance, prescription turnaround, and third-party pharmacy rules.  
* **Specification Blueprint**:

```
# STANDARD OPERATING PROCEDURE: Pharmacy Dispensing & Prescription Refills

## 1. Veterinary-Client-Patient Relationship (VCPR) & Legal Mandates
Under state veterinary licensing regulations and FDA compliance:
- **Annual Wellness Exam Requirement:** A physical examination performed within the preceding **365 days** is legally required to dispense or approve any prescription medication.
- **Therapeutic Blood Monitoring:** Chronic maintenance medications require periodic laboratory auditing before refills:
  - *NSAIDs (Carprofen/Meloxicam):* Chemistry panel (BUN, Creatinine, ALT) every 6 to 12 months.
  - *Thyroid / Phenobarbital / Incurin:* Serum concentration monitoring every 6 months.

## 2. Prescription Processing Turnaround
- **Standard In-House Refills:** Require **48 hours (2 business days)** notice for clinical review, technician calculation, and doctor authorization.
- **Compounded Specialty Formulations:** Require **5 business days** for compounding lab preparation.

## 3. Third-Party Online Pharmacy Authorizations (Chewy, 1-800-PetMeds)
To prevent medication counterfeit risks and improper storage, Harbor View does not approve external third-party digital faxes directly. Clients may pick up a complimentary written physical prescription to submit directly to their pharmacy of choice.
```

## **C. Canine & Feline Preventive Care Protocol Matrix**

* **Recommended File Format**: `preventive_care_matrix.json` (JSON formatted with 4-space indentation)  
* **Rationale**: Relational data schema defining core/non-core vaccination schedules, parasite prevention cadences, and diagnostic life-stage screening.  
* **Specification Blueprint**:

## **C. Canine & Feline Preventive Care Protocol Matrix**

* **Recommended File Format**: `preventive_care_matrix.json` (JSON formatted with 4-space indentation)  
* **Rationale**: Relational data schema defining core/non-core vaccination schedules, parasite prevention cadences, and diagnostic life-stage screening.  
* **Specification Blueprint**:

```json
{
    "preventive_protocol_metadata": {
        "clinic": "Harbor View Veterinary Clinic",
        "standard_version": "AAHA-AAFP-2024.2",
        "jurisdiction": "State Companion Animal Board",
        "currency": "USD"
    },
    "canine_protocols": {
        "core_vaccines": [
            {
                "vaccine_name": "Rabies (1-Year / 3-Year)",
                "initial_series_weeks": [16],
                "booster_cadence_years": 3,
                "state_legal_requirement": true,
                "target_pathogens": ["Rabies Rhabdovirus"]
            },
            {
                "vaccine_name": "DHPP / DA2PP",
                "initial_series_weeks": [8, 12, 16],
                "booster_cadence_years": 3,
                "state_legal_requirement": false,
                "target_pathogens": ["Distemper", "Adenovirus-2", "Parvovirus", "Parainfluenza"]
            }
        ],
        "non_core_lifestyle_vaccines": [
            {
                "vaccine_name": "Bordetella (Oral/Intranasal)",
                "lifestyle_criteria": "Boarding, grooming, dog daycare, or dog park exposure",
                "booster_cadence_months": 12
            },
            {
                "vaccine_name": "Leptospirosis (4-Serovar)",
                "lifestyle_criteria": "Exposure to standing puddle water, wildlife corridors, or rural trails",
                "booster_cadence_months": 12
            }
        ],
        "parasite_prevention": {
            "heartworm_screening": "Annual canine antigen SNAP test required prior to refilling preventative",
            "preventative_schedule": "Monthly year-round oral/topical isoxazoline and macrocyclic lactone"
        }
    }
}
```

## **D. New Client & Patient Registration Intake Policy**

* **Recommended File Format**: `PATIENT_REGISTRATION_INTAKE.md` (Markdown)  
* **Rationale**: Customer onboarding guidelines covering prior veterinary record transfers, appointment deposit schedules, and fear-free clinic arrival rules.  
* **Specification Blueprint**:

## **D. New Client & Patient Registration Intake Policy**

* **Recommended File Format**: `PATIENT_REGISTRATION_INTAKE.md` (Markdown)  
* **Rationale**: Customer onboarding guidelines covering prior veterinary record transfers, appointment deposit schedules, and fear-free clinic arrival rules.  
* **Specification Blueprint**:

```
# NEW CLIENT & PATIENT REGISTRATION INTAKE POLICY

## 1. Medical History & Record Transfer Requirements
- **Advance Records Submission:** Prior medical charts, surgical notes, and vaccination certificates must be received at least **24 hours prior** to the initial consultation.
- **Unverified Vaccines:** Animals without verifiable veterinary clinic medical records will be placed on an age-appropriate booster catch-up schedule to guarantee safety.

## 2. Appointment Booking Deposit & No-Show Policy
- **New Client Deposit:** A non-refundable **$65.00 deposit** (applied directly toward the exam fee) is required to secure the initial booking slot.
- **48-Hour Cancellation Window:** Deposits are transferable to a rescheduled date if notice is provided at least **48 hours** prior to the appointment. Cancellations under 48 hours forfeit deposit.

## 3. Fear-Free Arrival Protocols
- **Canine Patients:** Must remain secured on a non-retractable 6-foot nylon leash at all times.
- **Feline Patients:** Must be transported in a secure, hard-sided plastic carrier lined with a familiar blanket. Towel coverings sprayed with Feliway pheromones are available at the front entrance.
- **Reactive Patient Parking Check-In:** Guardians of anxious or dog-reactive pets may call reception from their vehicle to be ushered directly into an exam room, bypassing the lobby.
```

## **E. Urgent Care Triage & Emergency Referral Protocols**

* **Recommended File Format**: `EMERGENCY_TRIAGE_PROTOCOL.md` (Markdown)  
* **Rationale**: Clinical and customer-facing decision tree outlining what can be stabilized in an outpatient general practice versus immediate transfer to 24/7 specialty trauma hospitals.  
* **Specification Blueprint**:

## **E. Urgent Care Triage & Emergency Referral Protocols**

* **Recommended File Format**: `EMERGENCY_TRIAGE_PROTOCOL.md` (Markdown)  
* **Rationale**: Clinical and customer-facing decision tree outlining what can be stabilized in an outpatient general practice versus immediate transfer to 24/7 specialty trauma hospitals.  
* **Specification Blueprint**:

```
# PROTOCOL: Urgent Care Triage & Emergency Hospital Referral

## 1. Color-Coded Triage Classification System
Incoming urgent cases are assessed immediately upon arrival:

| Triage Category | Patient Clinical Presentation | Action / Clinical Pathway |
| :--- | :--- | :--- |
| **RED (Critical Emergency)** | Respiratory distress, collapse, active seizures, GDV / bloated abdomen, unresponsiveness | Immediate transfer to treatment bay; oxygen cage & IV catheter stabilization |
| **YELLOW (Urgent Priority)** | Male cat straining to urinate (suspected blocked cat), acute toxin ingestion, ocular injuries, deep lacerations | Exam within 30 minutes; pain relief & diagnostic ultrasound triage |
| **GREEN (Stable Outpatient)** | Mild ear infection, chronic skin itching, broken toenail without arterial bleed, limping with bearing weight | Scheduled same-day work-in appointment slot |

## 2. Outpatient Clinic Limitations & 24/7 Emergency Transfer
Harbor View is a day practice and does not offer overnight intensive care monitoring:
- **Transfer Criteria:** Patients requiring continuous IV fluid titration, arterial blood gas audits, blood transfusions, or overnight oxygen therapy are stabilized and transferred.
- **Designated Regional Referral Partner:** *Regional Animal Specialty & Emergency Center (24/7 ER)* — Phone: (555) 948-3700. Transport records and radiographs are transferred digitally.
```

## **F. Master Veterinary Support FAQ Knowledge Base**

* **Recommended File Format**: `faq_support_knowledgebase.json` (JSON formatted with 4-space indentation)  
* **Rationale**: Programmatic knowledge base for vector embedding, RAG retrieval pipelines, and automated customer assistance agents.  
* **Specification Blueprint**:

```json
{
    "knowledgebase_metadata": {
        "company": "Harbor View Veterinary Clinic",
        "system_id": "KB-HV-2024-V1",
        "total_entries": 5
    },
    "faqs": [
        {
            "id": "FAQ-SUR-001",
            "category": "Post-Operative Recovery",
            "question": "My dog took off her E-collar and licked her incision for a few minutes. What should I do?",
            "answer": "Immediately put the E-collar back on. Canine saliva contains heavy oral bacteria that can cause deep wound infections and dissolve absorbable sutures. Inspect the incision for redness, swelling, or opening of the wound. Contact our triage team at (555) 438-2323 to schedule an incision check or receive antibiotic ointment guidance.",
            "escalate_to_human": true
        },
        {
            "id": "FAQ-RX-002",
            "category": "Pharmacy & Refills",
            "question": "Why does my dog need a blood test before you refill his arthritis pain medication?",
            "answer": "Non-steroidal anti-inflammatory drugs (NSAIDs like Carprofen) are metabolized by the liver and kidneys. Routine blood testing every 6 to 12 months ensures your dog's organ function remains healthy and that the medication can continue to be filtered safely without risking organ toxicity.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-INT-003",
            "category": "Appointments & Intake",
            "question": "What should I bring to my new pet's first appointment?",
            "answer": "Please provide your pet's complete medical and vaccination records at least 24 hours in advance. For the visit, bring a fresh fecal sample (under 12 hours old), any current medications/supplements, and ensure dogs are on a 6-foot non-retractable leash and cats are inside a secure carrier.",
            "escalate_to_human": false
        },
        {
            "id": "FAQ-EMG-004",
            "category": "Urgent Care & Emergencies",
            "question": "My male cat is repeatedly going to the litter box, crying, and straining without producing urine. Is this an emergency?",
            "answer": "Yes, this is a life-threatening medical emergency. A blocked urethra in male cats causes toxic buildup of potassium and kidney failure within 24 to 48 hours. Bring your cat to our clinic immediately or go straight to the nearest 24/7 emergency hospital if we are closed.",
            "escalate_to_human": true
        },
        {
            "id": "FAQ-VAC-005",
            "category": "Vaccinations & Wellness",
            "question": "Does my indoor-only cat really need vaccines?",
            "answer": "Yes. Rabies vaccination is legally required by state law even for strictly indoor pets, as bats and wild vectors can enter homes. We also strongly recommend the FVRCP vaccine (feline viral rhinotracheitis, calicivirus, and panleukopenia) because these airborne and fomite-spread viruses can easily be brought indoors on human shoes and clothing.",
            "escalate_to_human": false
        }
    ]
}
```
