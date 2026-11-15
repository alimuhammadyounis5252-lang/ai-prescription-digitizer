---
title: AI Prescription Digitizer & Clinical Healthcare Intelligence
emoji: 💊
colorFrom: teal
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# AI-Powered Handwritten Prescription Digitization & Clinical Healthcare Intelligence

An assistive clinical intelligence system that transcribes handwritten doctor prescriptions using multimodal vision-language models, normalizes medications against the national Drug Regulatory Authority of Pakistan (DRAP) formulary, separates diagnostic lab tests, generates natural conversational Urdu dosage speech for rural patient accessibility, and exports HL7 FHIR-compliant electronic health records under mandatory Human-in-the-Loop pharmacist validation.

> **BS Artificial Intelligence Final Year Project (Session 2023–2027)**  
> **Department of Artificial Intelligence, The Islamia University of Bahawalpur (IUB)**  
> **Author:** Ali Muhammad Younis  
> **Clinical Role:** Assistive Clinical Intelligence (Human-in-the-Loop review mandatory; never auto-dispenses).

---

## 1. System Architecture

The pipeline enforces deterministic safety checks so that probabilistic vision-language outputs are strictly governed by clinical validation rules:

```
+------------------+     +-----------------------+     +-------------------------+
| Prescription     | --> | Image Quality Gate    | --> | Multimodal VLM          |
| Photo (JPG/PNG)  |     | (Resolution & Blur)   |     | (Groq / Qwen 2.5 28B)   |
+------------------+     +-----------------------+     +-------------------------+
                                                                    |
                                                                    v
+------------------+     +-----------------------+     +-------------------------+
| Human Pharmacist | <-- | DRAP Mega Formulary   | <-- | Deterministic Parser    |
| Review & Lock    |     | (1,055 Verified Meds) |     | (Dose, Frequency, Time) |
+------------------+     +-----------------------+     +-------------------------+
         |
         +--> [1] Conversational Urdu Neural Speech (ur-PK-UzmaNeural)
         +--> [2] HL7 FHIR v4.0.1 Bundle Export (MedicationRequest)
         +--> [3] Diagnostic Lab Test Separation (CBC, RBS, USG)
         +--> [4] Immutable Audit Trail & Pharmacist Verification Log
```

---

## 2. Key Clinical & Technical Features

- **Multimodal Handwriting OCR:** Transcribes authentic handwritten prescriptions using high-capacity vision-language modeling.
- **National DRAP Mega Formulary (1,055 Medicines):** Standardized against official Drug Regulatory Authority of Pakistan pharmaceutical registrations across all major therapeutic categories (Cardiology, Endocrinology, Gastroenterology, Antibiotics, Neurology, Dermatology, ENT, Pediatrics).
- **Diagnostic Lab Test Segregation:** Distinguishes diagnostic lab investigations (`CBC`, `RBS 256`, `U.S.G`, `HBsAg`, `Anti-HCV`, `HCG`) from medications, displaying them under separate clinical badges.
- **Natural Human Urdu Voice Engine:** Powered by Microsoft Edge Neural Speech (`ur-PK-UzmaNeural`), providing fluent, compassionate Urdu audio instructions (specifying drug name, form, strength, and schedule) to bridge literacy barriers.
- **HL7 FHIR v4.0.1 Interoperability:** Generates standardized `MedicationRequest` and `Provenance` resources ready for Electronic Health Record (EHR) and Hospital Information Management System (HIMS) ingestion.
- **Strict Human-in-the-Loop (HITL) Guardrail:** Implements patient safety protocols; unverified or ambiguous lines are flagged with red borders, requiring explicit pharmacist sign-off before record approval.

---

## 3. Clinical Safety Metrics & Evaluation

In clinical artificial intelligence, standard accuracy is insufficient because missing a prescribed medication (**False Negative**) can lead to severe patient harm or sepsis. Thus, this project prioritizes **Clinical Recall** and **$F_2$-Score**:

$$\text{Clinical Recall} = \frac{\text{True Positives}}{\text{True Positives} + \text{False Negatives}}$$

$$F_2 = \frac{5 \cdot \text{Precision} \cdot \text{Recall}}{4 \cdot \text{Precision} + \text{Recall}}$$

- **Clinical Recall ($\ge 99\%$ Target):** Guarantees that virtually all prescribed medications are captured for pharmacist review.
- **$F_2$-Measure:** Weighs recall twice as heavily as precision to minimize life-threatening omissions.
- **Character Error Rate (CER) & Word Error Rate (WER):** Standardized Levenshtein distance metrics computed across verified ground-truth test splits.

---

## 4. Quickstart Guide

### Prerequisites
- Python 3.10 or newer
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/alimuhammadyounis/ai-prescription-digitizer.git
   cd ai-prescription-digitizer
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the example environment file and add your model provider credentials:
   ```bash
   cp .env.example .env
   ```
   Configure `VLM_BASE_URL`, `VLM_MODEL`, and `VLM_API_KEY` in `.env`.

5. **Run the local clinical server:**
   ```bash
   python app.py
   ```
   Access the dashboard at `http://127.0.0.1:5000`.

---

## 5. Docker Deployment

The application is fully containerized and compatible with Linux servers, cloud providers, and container runtimes:

```bash
# Build the container
docker build -t rx-digitizer .

# Run container with volume persistence
docker run -d --name rx-digitizer -p 7860:7860 --env-file .env -v rx-records:/app/records rx-digitizer
```
Access the application on port `7860`.

---

## 6. Automated Testing & Verification

Execute the comprehensive automated test suite (covering line parsers, DRAP formulary lookups, Urdu speech synthesis, and FHIR schema validation):

```bash
pytest -v
```

---

## 7. Project Structure

```
├── app.py                      # Flask Application Server & Clinical REST APIs
├── evaluate.py                 # Ground-truth evaluation harness (CER, WER, Recall)
├── Dockerfile                  # Production container definition
├── requirements.txt            # Production dependencies
├── .env.example                # Template for environment configuration
├── rxcore/                     # Core Clinical Intelligence Engine
│   ├── recognizer.py           # Multimodal VLM vision client
│   ├── parser.py               # Deterministic clinical rules & dosage extractor
│   ├── formulary.py            # DRAP 1,055 reference matcher & look-alike guard
│   ├── urdu.py                 # Conversational Urdu patient instruction builder
│   ├── quality.py              # Image resolution & blur validation
│   ├── fhir.py                 # HL7 FHIR v4.0.1 resource generator
│   └── storage.py              # Pharmacist audit trail & record persistence
├── web/                        # Web Dashboard Frontend
│   ├── index.html              # Clinical user interface
│   ├── app.js                  # Client state, audio player & review handler
│   └── style.css               # Clinical styling & responsive layout
├── data/                       # Datasets & Knowledge Bases
│   ├── formulary.csv           # 1,055 DRAP-verified pharmaceutical entries
│   └── ground_truth/           # Benchmark labels and evaluation schema
└── docs/                       # Technical Documentation
    └── ARCHITECTURE.md         # Detailed architectural specification
```

---

## 8. Citation

If you utilize this system, dataset, or architectural methodology in your research, please cite:

```bibtex
@misc{younis2026prescription,
  author = {Ali Muhammad Younis},
  title = {AI-Powered Handwritten Prescription Digitization & Clinical Healthcare Intelligence},
  howpublished = {Department of Artificial Intelligence, The Islamia University of Bahawalpur},
  year = {2026},
  note = {BS Artificial Intelligence Final Year Project}
}
```

---

## 9. License

This project is released under the **MIT License**.
