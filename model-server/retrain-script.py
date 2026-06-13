import json, random, time, os, sys

def collect_data():
    print("Coletando dados novos...")
    data = {"n_samples": random.randint(800,1200), "features": 5,
            "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    print(json.dumps({"step":"collect","status":"ok",**data}))
    return data

def train_model(data):
    print("Treinando modelo...")
    time.sleep(1)
    model = {"algorithm":"RandomForest","n_estimators":100,
             "n_samples_train":int(data["n_samples"]*0.8)}
    print(json.dumps({"step":"train","status":"ok",**model}))
    return model

def evaluate_model(model):
    print("Avaliando modelo...")
    auc = round(random.uniform(0.78,0.92),4)
    drift = round(random.uniform(0.05,0.15),4)
    metrics = {"auc_roc":auc,"drift_score":drift,"passed":auc>=0.78 and drift<=0.20}
    print(json.dumps({"step":"evaluate","status":"ok",**metrics}))
    return metrics

def decide(metrics):
    if metrics["passed"]:
        tag = f"v{int(time.time())}"
        print(json.dumps({"step":"decide","action":"promote","new_tag":tag,"auc_roc":metrics["auc_roc"]}))
    else:
        print(json.dumps({"step":"decide","action":"reject","auc_roc":metrics["auc_roc"]}))
        sys.exit(1)

step = os.getenv("STEP","all")
if step == "collect":
    r = collect_data()
    open("/tmp/data.json","w").write(json.dumps(r))
elif step == "train":
    d = json.load(open("/tmp/data.json"))
    r = train_model(d)
    open("/tmp/model.json","w").write(json.dumps(r))
elif step == "evaluate":
    m = json.load(open("/tmp/model.json"))
    r = evaluate_model(m)
    open("/tmp/metrics.json","w").write(json.dumps(r))
elif step == "decide":
    m = json.load(open("/tmp/metrics.json"))
    decide(m)
else:
    decide(evaluate_model(train_model(collect_data())))
