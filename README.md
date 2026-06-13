# ml-gitops — Canary Inteligente de Modelos ML

> Stack MLOps de alto nível com entrega contínua de modelos via GitOps, análise automática de qualidade e governança por policy.

---

## Visão Geral

A maioria dos times faz canary de **infraestrutura** — CPU, memória, taxa de erro HTTP. Este projeto faz canary de **qualidade de modelo**: um novo modelo só chega a 100% do tráfego se suas métricas de negócio (AUC-ROC, drift de distribuição, latência P99) ficarem acima dos thresholds configurados durante todo o rollout. Se qualquer métrica degradar, o rollback acontece automaticamente — sem intervenção humana.

```
git push → Argo CD detecta → Argo Rollouts divide tráfego
                                      ↓
                         10% tráfego → canary (v2)
                         90% tráfego → stable (v1)
                                      ↓
                         Prometheus coleta métricas do canary
                                      ↓
                    AnalysisTemplate avalia: AUC ≥ 0.75? Drift ≤ 0.30?
                         ↙                              ↘
                    PASS → avança 50% → 100%      FAIL → rollback automático
```

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                         │
│                    github.com/sereno4/ml-gitops                  │
│                                                                   │
│  models/recommendation/    policies/         logging/            │
│  ├── rollout.yaml          ├── require-*     └── fluent-bit-*    │
│  ├── services.yaml         └── disallow-*                        │
│  └── analysis-template.yaml                                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ git push
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster (kind)                     │
│                                                                   │
│  ┌─────────────┐    ┌──────────────────────────────────────┐    │
│  │   Argo CD   │───▶│         Argo Rollouts                │    │
│  │  (GitOps)   │    │                                      │    │
│  │             │    │  stable (v1) ──── 90% tráfego        │    │
│  │  Sync every │    │  canary (v2) ──── 10% tráfego        │    │
│  │  3 minutes  │    │                                      │    │
│  └─────────────┘    │  AnalysisRun ──── consulta Prometheus│    │
│                     └──────────────────────────────────────┘    │
│                                        │                         │
│  ┌─────────────┐    ┌──────────────────▼───────────────────┐    │
│  │   Kyverno   │    │              Prometheus               │    │
│  │  (Policies) │    │                                      │    │
│  │             │    │  model_auc_roc{version="v2"}         │    │
│  │  Bloqueia   │    │  model_drift_score{version="v2"}     │    │
│  │  pods sem   │    │  model_inference_latency_seconds     │    │
│  │  padrão     │    └──────────────────────────────────────┘    │
│  └─────────────┘                       │                         │
│                                        │ scrape /metrics         │
│  ┌─────────────┐    ┌──────────────────▼───────────────────┐    │
│  │  Fluent Bit │    │         Model Server (FastAPI)        │    │
│  │  (Logging)  │◀───│                                      │    │
│  │             │    │  POST /predict  → JSON log           │    │
│  │  Coleta     │    │  GET  /metrics  → Prometheus format  │    │
│  │  logs JSON  │    │  GET  /status   → health + métricas  │    │
│  │  em tempo   │    │  GET  /simulate/degrade → testes     │    │
│  │  real       │    └──────────────────────────────────────┘    │
│  └─────────────┘                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack de Tecnologias

| Componente | Tecnologia | Versão | Papel |
|---|---|---|---|
| Entrega contínua | Argo CD | stable | GitOps — sincroniza Git → cluster |
| Canary | Argo Rollouts | latest | Divide tráfego e avalia métricas |
| Métricas | Prometheus | community/prometheus | Coleta AUC, drift, latência |
| Logging | Fluent Bit | 5.0.7 | Coleta logs de predição JSON |
| Governança | Kyverno | kyverno/kyverno | Policies de segurança e padrão |
| Model server | FastAPI + uvicorn | 0.110.0 | Serve predições e expõe métricas |
| Cluster local | kind | v1.31.0 | Kubernetes em Docker |

---

## Decisões Técnicas

### Por que `Rollout` e não `Deployment`?

O `Deployment` nativo do Kubernetes só sabe fazer rolling update — troca pods gradualmente mas sem nenhuma lógica de análise. O `Rollout` do Argo pausa entre fases, consulta o Prometheus, e faz rollback automático se as métricas não passarem. Para ML isso é crítico: um modelo pode estar com CPU e memória normais mas degradando silenciosamente em AUC — o `Deployment` não detecta isso, o `Rollout` sim.

### Por que métricas de negócio e não só infraestrutura?

Um modelo que começa a prever majoritariamente a classe majoritária tem zero erros HTTP, CPU normal, latência normal — mas está destruindo conversão em silêncio. O `AnalysisTemplate` foi configurado para monitorar:

- **AUC-ROC ≥ 0.75** — capacidade discriminativa mínima do modelo
- **Drift score ≤ 0.30** — distribuição de entrada não pode mudar demais em relação ao treino
- **P99 latência < 500ms** — SLA de resposta do model server

### Por que Kyverno e não OPA/Gatekeeper?

Kyverno usa YAML nativo do Kubernetes para escrever policies — sem necessidade de aprender Rego. Para um time de ML que já lida com YAML de manifests, a curva de aprendizado é zero. As três policies implementadas garantem que **nenhum pod sobe em `ml-production` sem**:

1. Anotações do Prometheus (`prometheus.io/scrape`, `port`, `path`)
2. Resource limits de CPU e memória definidos
3. Label `team` para rastreabilidade de custo
4. Imagem com tag explícita (sem `:latest`)

### Por que Fluent Bit e não Logstash/Fluentd?

Fluent Bit consome ~1MB de memória vs ~50MB do Fluentd. Em um cluster com dezenas de pods de modelo rodando como DaemonSet, isso faz diferença real. O pipeline implementado filtra apenas logs com `"event":"prediction"` — não coleta logs de health check ou métricas, reduzindo volume de dados.

### Por que o model server loga no stdout?

Logs no stdout seguem o padrão 12-factor app — o container não precisa saber para onde os logs vão. O Fluent Bit coleta de `/var/log/containers/*.log` (que é onde o kubelet escreve o stdout dos containers) e decide o destino. Hoje vai para stdout do Fluent Bit; amanhã vai para Loki, S3 ou Kafka sem mudar uma linha do model server.

---

## Estrutura do Repositório

```
ml-gitops/
├── models/
│   └── recommendation/
│       ├── namespace.yaml          # Namespace ml-production
│       ├── rollout.yaml            # Argo Rollout com estratégia canary
│       ├── services.yaml           # Services stable e canary
│       └── analysis-template.yaml  # Queries Prometheus para validação
├── policies/
│   ├── require-prometheus-annotations.yaml  # Obriga scrape annotations
│   ├── require-resource-limits.yaml         # Obriga limits + label team
│   └── disallow-latest-tag.yaml             # Proíbe tag :latest
├── logging/
│   └── fluent-bit-configmap.yaml   # Pipeline de coleta de predições
├── applications/
│   ├── argocd-project.yaml         # AppProject ml-platform
│   └── argocd-app.yaml             # Application apontando para este repo
└── model-server/
    ├── main_v1.py                  # Model server v1 (stable)
    ├── main_v2.py                  # Model server v2 (canary) com JSON logging
    ├── Dockerfile.v1
    └── Dockerfile.v2
```

---

## Instalação

### Pré-requisitos

```bash
# Ferramentas necessárias
kubectl version --client   # >= 1.28
kind version               # >= 0.20
helm version               # >= 3.12
docker --version           # >= 24.0
kubectl argo rollouts version
```

### 1. Cluster

```bash
kind create cluster --name ml-canary
kubectl cluster-info --context kind-ml-canary
```

### 2. Argo Rollouts

```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# Plugin kubectl
curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x kubectl-argo-rollouts-linux-amd64
sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts
```

### 3. Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/prometheus \
  --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set prometheus-pushgateway.enabled=false
```

### 4. Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Senha inicial
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo ""
```

### 5. Fluent Bit

```bash
helm repo add fluent https://fluent.github.io/helm-charts

helm install fluent-bit fluent/fluent-bit \
  --namespace logging --create-namespace \
  --values logging/fluent-bit-values.yaml
```

### 6. Kyverno

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/

helm install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.enabled=false \
  --set cleanupController.enabled=false \
  --set reportsController.enabled=false
```

### 7. Build e deploy do model server

```bash
cd model-server
docker build -f Dockerfile.v1 -t recommendation-model:v1 .
docker build -f Dockerfile.v2 -t recommendation-model:v2 .

kind load docker-image recommendation-model:v1 --name ml-canary
kind load docker-image recommendation-model:v2 --name ml-canary

cd ..
kubectl apply -f models/recommendation/
kubectl apply -f policies/
```

---

## Como Testar

### Verificar o estado do Rollout

```bash
kubectl argo rollouts get rollout recommendation-model \
  -n ml-production --watch
```

### Disparar um canary

```bash
kubectl argo rollouts set image recommendation-model \
  model-server=recommendation-model:v2 \
  -n ml-production
```

### Simular degradação e observar rollback

```bash
# Terminal 1 — observa
kubectl argo rollouts get rollout recommendation-model \
  -n ml-production --watch

# Terminal 2 — degrada o canary
kubectl port-forward -n ml-production svc/recommendation-model-canary 8082:80 &
curl http://localhost:8082/simulate/degrade
curl http://localhost:8082/status
# → {"healthy": false, "auc_roc": 0.55, "drift_score": 0.85}
```

### Verificar métricas no Prometheus

```bash
kubectl port-forward -n monitoring svc/prometheus-server 9090:80 &
curl -s "http://localhost:9090/api/v1/query?query=model_auc_roc" | python3 -m json.tool
```

### Testar policies do Kyverno

```bash
# Deve ser BLOQUEADO — sem anotações Prometheus
kubectl run test --image=nginx -n ml-production

# Deve ser BLOQUEADO — tag :latest
kubectl run test --image=nginx:latest -n ml-production
```

### Ver logs de predição no Fluent Bit

```bash
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit -f
```

---

## Métricas Monitoradas

| Métrica | Tipo | Threshold | Ação se violar |
|---|---|---|---|
| `model_auc_roc` | Gauge | ≥ 0.75 | Rollback automático |
| `model_drift_score` | Gauge | ≤ 0.30 | Rollback automático |
| `model_inference_latency_seconds` (P99) | Histogram | < 500ms | Rollback automático |
| `model_predictions_total` | Counter | — | Observabilidade |

---

## Limitações Conhecidas e Roadmap

### O que funciona hoje

- Canary com divisão real de tráfego (10% → 50% → 100%)
- Kyverno bloqueando pods fora do padrão
- Fluent Bit coletando logs JSON de predição em tempo real
- Prometheus raspando métricas dos pods via anotações
- Argo CD conectado ao GitHub

### O que é simulado / incompleto

**Rollback por degradação real de AUC** — o rollback automático que aconteceu durante o desenvolvimento foi por `NaN` (canary sem dados no Prometheus ainda), não por AUC < 0.75. Para o teste definitivo funcionar é preciso um `initialDelay` no `AnalysisTemplate` que aguarde o canary acumular dados antes de avaliar.

**Destino do Fluent Bit** — os logs de predição estão indo para `stdout` do Fluent Bit. Em produção iriam para Loki (para queries), S3 (para retraining) ou Kafka (para streaming de features).

**Imagens locais** — o model server usa `imagePullPolicy: Never` com imagens carregadas via `kind load`. Em produção usaria um registry (ECR, GCR, Harbor).

**AnalysisTemplate com `inconclusiveLimit`** — sem essa configuração, qualquer `NaN` do Prometheus causa rollback. O template precisa de `inconclusiveLimit: 3` para tolerar os primeiros scrapes sem dados.

### Roadmap

```
v0.1 (atual)   ── Canary + Prometheus + Kyverno + Fluent Bit + Argo CD
v0.2           ── Loki como destino do Fluent Bit + Grafana dashboard
v0.3           ── Retraining automático com Argo Workflows
v0.4           ── eBPF para observabilidade de chamadas de sistema
v0.5           ── Wasm para feature engineering portátil no edge
```

---

## Referências

- [Argo Rollouts — Analysis & Progressive Delivery](https://argoproj.github.io/argo-rollouts/features/analysis/)
- [Kyverno Policies](https://kyverno.io/policies/)
- [Fluent Bit — Kubernetes Filter](https://docs.fluentbit.io/manual/pipeline/filters/kubernetes)
- [Prometheus — Instrumentation Best Practices](https://prometheus.io/docs/practices/instrumentation/)

---

## Autor

**Daniel** — [@sereno4](https://github.com/sereno4)

> Projeto desenvolvido como estudo prático de MLOps de alto nível.
> Stack real, problemas reais, soluções reais.
