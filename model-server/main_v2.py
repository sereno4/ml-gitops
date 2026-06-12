import random, time, os
from fastapi import FastAPI
from prometheus_client import Gauge, Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

app = FastAPI()
VERSION = "v2"

auc   = Gauge("model_auc_roc", "AUC-ROC", ["version"])
drift = Gauge("model_drift_score", "Drift", ["version"])
lat   = Histogram("model_inference_latency_seconds", "Latency", ["version"],
                  buckets=[0.01,0.05,0.1,0.25,0.5,1.0])
preds = Counter("model_predictions_total", "Predictions", ["version","outcome"])

auc.labels(version=VERSION).set(0.85)
drift.labels(version=VERSION).set(0.07)

@app.get("/health/ready")
def ready(): return {"status": "ready", "version": VERSION}

@app.get("/health/live")
def live(): return {"status": "alive", "version": VERSION}

@app.post("/predict")
def predict():
    start = time.time()
    time.sleep(random.uniform(0.01, 0.04))
    score = random.random()
    outcome = "positive" if score > 0.5 else "negative"
    cur = auc.labels(version=VERSION)._value.get()
    auc.labels(version=VERSION).set(max(0.5, min(1.0, cur + random.uniform(-0.005,0.005))))
    cur_d = drift.labels(version=VERSION)._value.get()
    drift.labels(version=VERSION).set(max(0.0, min(1.0, cur_d + random.uniform(-0.003,0.003))))
    lat.labels(version=VERSION).observe(time.time() - start)
    preds.labels(version=VERSION, outcome=outcome).inc()
    return {"score": round(score,4), "outcome": outcome, "version": VERSION}

@app.get("/simulate/degrade")
def degrade():
    auc.labels(version=VERSION).set(0.55)
    drift.labels(version=VERSION).set(0.85)
    return {"message": "degradado", "auc": 0.55, "drift": 0.85}

@app.get("/simulate/recover")
def recover():
    auc.labels(version=VERSION).set(0.85)
    drift.labels(version=VERSION).set(0.07)
    return {"message": "recuperado"}

@app.get("/metrics")
def metrics(): return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/status")
def status():
    a = auc.labels(version=VERSION)._value.get()
    d = drift.labels(version=VERSION)._value.get()
    return {"version": VERSION, "auc_roc": round(a,4), "drift_score": round(d,4), "healthy": a>=0.75 and d<=0.30}
