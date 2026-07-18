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
3. **ML Lexical Classification**: A Random Forest classifier using 20 lexical features to detect disposable, bot-generated, and high-risk addresses. Includes a Domain-Aware Heuristic Engine with a live disposable domain cache.
4. **SMTP Handshake Diagnostics**: Performs a safe SMTP EHLO/RCPT probe (without sending any actual email). Detects catch-all domains and greylisted servers.

---

## 💻 How to Run the Project

You can run the system easily via Docker, or run it directly on your local machine using Python.

### Option 1: Using Docker Compose (Recommended - Includes Redis)

Docker automatically handles all system dependencies, Redis caching, and pre-trains the Machine Learning model.

1. Ensure Docker and Docker Compose are installed.
2. Start the application stack:
   ```bash
   docker-compose up -d --build
   ```
3. Open your browser and navigate to [http://localhost:8000](http://localhost:8000) to view the Admin Dashboard.

### Option 2: Running Locally with Python

1. Ensure you have **Python 3.11+** installed.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Pre-train the Machine Learning model:
   ```bash
   python -c "from app.services.ml_model import MLModel; MLModel()"
   ```
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
