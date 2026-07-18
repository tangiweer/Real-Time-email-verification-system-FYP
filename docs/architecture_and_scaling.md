# Architecture and Scaling Guide

This document outlines the architectural decisions and advanced concepts implemented in the Email Verification project to ensure robustness, performance, and accuracy in a production environment.

## 1. Asynchronous Worker Pool & Concurrency
The framework is built entirely using Python's `asyncio` ecosystem, specifically the FastAPI web framework and `aiosmtplib` for network calls. 

- **Concurrency Limits**: The `SMTPHandler` uses an `asyncio.Semaphore` to restrict the number of concurrent outgoing SMTP connections (to prevent immediately overwhelming port 25 on local firewalls).
- **Worker Pools**: In a production environment, the FastAPI application should be run with a tool like `gunicorn` combined with `uvicorn` workers (e.g. `gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app`). This spins up multiple asynchronous worker processes to fully utilize CPU cores.
- **Jitter Delays**: We implement randomized "jitter" (variable delay timers) prior to executing our SMTP probes. This helps smooth out spikes in traffic to major mail servers (like Gmail or Outlook), drastically reducing the risk of IP rate-limiting or greylisting.

## 2. Distributed Caching Layer (Redis)
To support multi-worker or horizontally scaled deployments, the application integrates with **Redis** as a caching layer.

- **Catch-All Resolution**: Detecting a Catch-All server is expensive and risks blacklisting. When a domain is identified as a Catch-All via a randomized canary probe, that result is cached in Redis for 1 hour. All subsequent requests across all worker nodes for that domain instantly bypass the SMTP probe and rely exclusively on the ML and DNS layers.
- **ML Model Caching**: The Random Forest model executes complex feature extraction and decision-tree logic. Predictions (the ML probability scores) are cached in Redis using the email address as a key. This reduces latency to sub-milliseconds for repeated verification attempts of similar lexical structures.

## 3. IP Rotation and Proxies
Running thousands of SMTP probes from a single IP address (such as an AWS instance or a University campus IP) is a guaranteed way to get the server's IP address blacklisted by Spamhaus.

- **Proxy Layer Architecture**: While not actively turned on in the academic repository, the `aiosmtplib` client can be wrapped to utilize SOCKS5 or HTTP proxies.
- **Implementation Strategy**: A production deployment would subscribe to an IP Proxy Pool service (e.g., Bright Data). The application would route SMTP handshakes randomly through proxy exit nodes. This ensures that the target mail server sees connections coming from thousands of different IP addresses, thereby avoiding rate limits and IP blocking.

## 4. ML Model Drift & Retraining (CI/CD)
The Random Forest model is trained on a snapshot of data, but spam bot behavior and email generation algorithms (e.g. temporary email domains) change over time. This phenomenon is known as **Model Drift**.

### Handling Drift via CI/CD Pipeline
1. **Feedback Loop**: Production instances should log false positives (legitimate emails marked as bots) and false negatives (bounced emails that were marked as valid).
2. **Automated Retraining**: A CI/CD pipeline (e.g., GitHub Actions) is scheduled weekly. It pulls the latest production logs and adds them to the training dataset.
3. **Evaluation**: The pipeline retrains the Random Forest model and runs it against a held-out benchmark set. If the precision and F1 scores are higher than the current production model, the new weights are saved.
4. **Blue/Green Deployment**: The new `.pkl` model weights are loaded dynamically into the Redis cache or deployed alongside a new container version to ensure zero downtime.

## 5. High-Quality Artifact Output Strategy
During model training and evaluation (e.g., in external notebooks or CI pipelines), performance metrics and visual analytics are exported as formal artifacts.
- **Evaluation Directory**: All generated plots such as ROC curves, Precision-Recall curves, and Reliability Diagrams should be saved directly into the `evaluation/` directory.
- **Empirical Validation**: Including these visualizations along with statistical tests like the empirical Brier Score or McNemar’s Significance Test provides concrete, academic-grade evidence of the model's performance and reliability.

By integrating robust async workers, Redis caching, proxy architecture, automated retraining, and empirical artifact generation, this verification pipeline is highly resilient, scalable, and academically rigorous.
