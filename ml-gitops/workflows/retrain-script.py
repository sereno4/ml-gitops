"""
Script de retraining automático
Roda como step dentro do Argo Workflow
"""
import json
import random
import time
import os
import sys

# Simula sklearn — em produção seria:
# from sklearn.ensemble import RandomForestClassifier
# from sklearn.metrics import roc_auc_score

def collect_data():
    """Step 1: Coleta dados novos"""
    print("Coletando dados novos...")
    n_samples = random.randint(800, 1200)
    data = {
        "n_samples": n_samples,
        "features": 5,
        "source": "s3://ml-data/predictions/recent/",
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    print(json.dumps({"step": "collect", "status": "ok", **data}))
    return data

def train_model(data):
    """Step 2: Treina o modelo"""
    print("Treinando modelo...")
    time.sleep(2)  # Simula treino

    # Em produção: model.fit(X_train, y_train)
    model_info = {
        "algorithm": "RandomForest",
        "n_estimators": 100,
        "n_samples_train": int(data["n_samples"] * 0.8),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    print(json.dumps({"step": "train", "status": "ok", **model_info}))
    return model_info

def evaluate_model(model_info):
    """Step 3: Avalia no validation set"""
    print("Avaliando modelo...")

    # Simula métricas de avaliação
    # Em produção: auc = roc_auc_score(y_val, model.predict_proba(X_val)[:,1])
    auc = round(random.uniform(0.78, 0.92), 4)
    drift = round(random.uniform(0.05, 0.15), 4)

    metrics = {
        "auc_roc": auc,
        "drift_score": drift,
        "n_samples_val": int(model_info.get("n_samples_train", 800) * 0.2),
        "passed": auc >= 0.78 and drift <= 0.20
    }
    print(json.dumps({"step": "evaluate", "status": "ok", **metrics}))
    return metrics

def decide(metrics):
    """Step 4: Decide se promove o modelo"""
    if metrics["passed"]:
        new_tag = f"v{int(time.time())}"
        print(json.dumps({
            "step": "decide",
            "action": "promote",
            "new_tag": new_tag,
            "auc_roc": metrics["auc_roc"],
            "message": f"Modelo aprovado — tag {new_tag} será deployada via GitOps"
        }))
        return new_tag
    else:
        print(json.dumps({
            "step": "decide",
            "action": "reject",
            "auc_roc": metrics["auc_roc"],
            "message": "Modelo rejeitado — AUC abaixo do threshold 0.78"
        }))
        sys.exit(1)

if __name__ == "__main__":
    step = os.getenv("STEP", "all")

    if step == "collect":
        result = collect_data()
        with open("/tmp/data.json", "w") as f:
            json.dump(result, f)

    elif step == "train":
        with open("/tmp/data.json") as f:
            data = json.load(f)
        result = train_model(data)
        with open("/tmp/model.json", "w") as f:
            json.dump(result, f)

    elif step == "evaluate":
        with open("/tmp/model.json") as f:
            model_info = json.load(f)
        result = evaluate_model(model_info)
        with open("/tmp/metrics.json", "w") as f:
            json.dump(result, f)

    elif step == "decide":
        with open("/tmp/metrics.json") as f:
            metrics = json.load(f)
        decide(metrics)

    else:
        # Roda tudo em sequência (modo local)
        data = collect_data()
        model = train_model(data)
        metrics = evaluate_model(model)
        decide(metrics)
