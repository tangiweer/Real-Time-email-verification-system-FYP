# Email Existence Verification Framework

Final Year Project — Staffordshire University (Weerakotuwa, 2026)

A full-stack email-verification system built around a four-stage Chain of Responsibility pipeline:

1. Syntax validation
2. DNS/MX record verification
3. Machine-learning lexical risk classification and disposable-domain heuristics
4. SMTP handshake diagnostics (no email is sent)

The repository contains the FastAPI backend, React/Vite frontend, model-training and evaluation code, automated tests, Docker configuration, and dependency manifests.

## Project structure

| Path | Purpose |
| --- | --- |
| `app/` | FastAPI API, authentication, database models, verification pipeline, and services |
| `frontend/` | React/Vite dashboard source code |
| `train_model_colab.py` | Reproducible training, comparison, validation, and model-export script |
| `data/build_evaluation_dataset.py` | Script that constructs the evaluation dataset from an external domain database |
| `evaluation/` | Domain-aware splitting, metrics, baselines, attribution, latency, OOD, and report generation |
| `tests/` | Pytest automated tests |
| `models/rf_model.joblib.metadata.json` | Model feature/schema metadata; the binary model is deliberately excluded |
| `docs/architecture_and_scaling.md` | Architecture, constraints, and scaling notes |

## Requirements

- Python 3.11 or later
- Node.js 22 (for local frontend development) and npm
- Docker Desktop and Docker Compose (optional, recommended for the complete stack)

Python dependencies are pinned in `requirements.txt`; JavaScript dependencies are locked in `frontend/package-lock.json`.

## Run with Docker Compose

1. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

2. Replace every placeholder in `.env` with values appropriate for your environment. Never commit this file.

3. Place the trained artifact at `models/rf_model.joblib` if ML classification is required. This binary is not included in the submission; see “Training and data” below.

4. Start the services:

   ```bash
   docker-compose up -d --build
   ```

5. Open http://localhost:8000. The interactive API documentation is available at http://localhost:8000/docs.

`MOCK_SMTP=1` is suitable only for local demonstrations. Real SMTP recipient probes are commonly blocked or greylisted; in those cases the system returns an uncertain result.

## Run locally

Install backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

For frontend-only development in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

## Tests and evaluation

Run the automated test suite from the repository root:

```bash
pytest
```

Run the evaluation workflow (using a supplied dataset or its configured generator inputs):

```bash
python -m evaluation.run_evaluation --dataset path/to/evaluation_dataset.csv
```

Generated reports are excluded from submission because they can be recreated by these scripts.

## Training and data

The training implementation is complete in `train_model_colab.py`. It supports either:

```bash
python train_model_colab.py --data path/to/labelled_emails.csv
```

or separate datasets:

```bash
python train_model_colab.py --valid-data path/to/valid.csv --invalid-data path/to/invalid.csv
```

For a single CSV, required columns are `email` and `label`, where `0` is legitimate and `1` is disposable/high-risk. The script applies domain-disjoint splitting, compares candidate classifiers, reports metrics, and exports `rf_model.joblib`. Copy the artifact to `models/rf_model.joblib` only when running the application locally.

Datasets, database files, generated reports, and trained model binaries are intentionally excluded from this repository/submission. The included source code shows how each is loaded, processed, trained, and evaluated.

## Submission contents and exclusions

This source submission includes all implementation code, configuration, tests, dependency manifests, and documentation. It deliberately excludes:

- datasets and generated CSV/SQLite files;
- trained model binaries (`*.joblib`, `*.pt`, `*.pth`, `*.h5`, `*.keras`, `*.onnx`, `*.pkl`);
- Python virtual environments and installed packages;
- `node_modules`, frontend build output, caches, coverage, and temporary files;
- `.env` and any secrets.

The root `.gitignore` enforces these exclusions for GitHub. The supplied submission ZIP follows the same rules.

## Further documentation

See [Architecture and Scaling Guide](docs/architecture_and_scaling.md) for design decisions, limitations, and evaluation context.
