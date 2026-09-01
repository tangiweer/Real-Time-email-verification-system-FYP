# Email Existence Verification Framework

A 4-layer Chain of Responsibility pipeline combining Syntax Analysis, DNS/MX Verification, Machine Learning Classification, and SMTP Diagnostics for real-time email verification.

*Final Year Project — Staffordshire University (Weerakotuwa, 2026)*

---

## 🚀 Overview

This framework provides a robust, multi-layered approach to email verification, designed to be integrated into user onboarding flows to protect deliverability and prevent spam accounts.

It features a **beautiful, real-time Admin Dashboard** to visualize the pipeline in action.

### The 4-Layer Pipeline

1. **Syntax Analysis**: Validates email format against RFC 5322 / RFC 5321 rules using regex. Rejects malformed inputs immediately with zero network calls.
2. **DNS MX Verification**: Queries DNS for MX records to confirm the domain can actually receive email. Gracefully handles NXDOMAIN, NoAnswer, and timeouts.
3. **ML Lexical Classification**: A Random Forest classifier using 18 lexical features to detect disposable, bot-generated, and high-risk addresses. It uses raw class-probability scores, not calibrated probabilities, and includes a Domain-Aware Heuristic Engine with a live disposable-domain cache.
4. **SMTP Handshake Diagnostics**: Performs a safe SMTP EHLO/RCPT probe (deep SMTP – high-confidence results without sending email, SMTP handshake – Mail server accepts the recipient (no message sent)). Detects catch-all domains and greylisted servers.

---

## 💻 How to Run the Project

You can run the system easily via Docker, or run it directly on your local machine using Python.

### Option 1: Using Docker Compose (Recommended - Includes Redis)

Docker automatically handles all system dependencies, Redis caching, and includes the trained Machine Learning model. Before startup, configure real secrets and an SMTP identity; mailbox probes may be blocked by providers and then correctly return `uncertain`.

1. Ensure Docker and Docker Compose are installed.
2. Create your local configuration and replace every placeholder with a long, random value and a domain you control:
   ```bash
   cp .env.example .env
   ```
3. Start the application stack:
   ```bash
   docker-compose up -d --build
   ```
4. Open [http://localhost:8000](http://localhost:8000), enter the configured API key in the Dashboard, and use the protected verification tools. The key is kept only for that browser session.

### Option 2: Running Locally with Python

1. Ensure you have **Python 3.11+** installed.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Ensure `models/rf_model.joblib` is present. To retrain it, use
   [`train_model_colab.py`](train_model_colab.py) in Google Colab and copy the
   exported artifact into the `models/` directory.
4. Start the FastAPI backend server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
5. Open your browser and navigate to [http://localhost:8000](http://localhost:8000) to view the Admin Dashboard.

---

## 📚 API Documentation

Once the server is running, interactive API documentation (Swagger UI) is automatically generated and available at:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## 📚 Advanced Architecture & Scaling

To understand how this project mitigates examiner "trap questions" (like SMTP block lists, ML latency, and model drift), please read the [Architecture and Scaling Guide](docs/architecture_and_scaling.md).

---

## 🧪 Running Tests

The project includes a comprehensive test suite using `pytest`. To run the tests, ensure you have installed the requirements, and then run:

```bash
pytest
```
## 📊 Research Question Answers

### RQ(a) — Registration impact (Partial)

- The `/register` endpoint is implemented and stores new user records in the SQLite database.
- While we currently do not have real‑world bounce‑rate or A/B‑test data, the system logs registration events (timestamp, email verification outcome, and latency) in `data/registrations.log`. This log can later be aggregated to compute bounce rates or run controlled experiments by toggling the verification step.
- **Future work:** Deploy a feature flag to enable/disable verification for a control group and collect metrics via the logging infrastructure.

### RQ(e) — UX & perceived speed (Partial)

- The React dashboard streams per‑layer results and confidence scores using WebSocket connections, giving users immediate visual feedback.
- Each pipeline step is displayed with a spinner that turns into a success/failure badge, reducing perceived latency.
- While we have not conducted a formal user study, we designed the UI following best‑practice heuristics: concise status messages, colour‑coded results, and a “Total verification time” counter.
- **Future work:** Run a usability survey and capture quantitative SUS scores to fully answer this research question.
