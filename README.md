ml-gitops — Stack MLOps de Alto Nível


Canary inteligente, GitOps, retraining automático, observabilidade com eBPF e pipeline de logs com Loki + Grafana.




O Problema que Este Projeto Resolve

A maioria dos times faz canary de infraestrutura — CPU, memória, taxa de erro HTTP. Um modelo pode estar com CPU normal, latência normal, zero erros HTTP — e estar destruindo conversão em silêncio porque o AUC caiu de 0.85 para 0.55.

Este projeto faz canary de qualidade de modelo: um novo modelo só chega a 100% do tráfego se suas métricas de negócio (AUC-ROC, drift de distribuição, latência P99) ficarem acima dos thresholds configurados durante todo o rollout. Se qualquer métrica degradar, o rollback acontece automaticamente — sem intervenção humana.


Arquitetura

┌─────────────────────────────────────────────────────────────────────┐
│                      GitHub (sereno4/ml-gitops)                      │
│                                                                       │
│  models/recommendation/   policies/    logging/    workflows/  ebpf/ │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ git push
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster (kind)                          │
│                                                                       │
│  ┌──────────────┐   ┌─────────────────────────────────────────┐     │
│  │   Argo CD    │──▶│            Argo Rollouts                 │     │
│  │   (GitOps)   │   │                                         │     │
│  │              │   │  stable (v1) ── 90% tráfego             │     │
│  │  sync: 3min  │   │  canary (v2) ── 10% tráfego             │     │
│  └──────────────┘   │                                         │     │
│                     │  AnalysisRun ── consulta Prometheus      │     │
│  ┌──────────────┐   └─────────────────────────────────────────┘     │
│  │   Kyverno    │                      │                             │
│  │  (Policies)  │   ┌──────────────────▼──────────────────────┐     │
│  │              │   │             Prometheus                    │     │
│  │  bloqueia    │   │  model_auc_roc{version="v2"}             │     │
│  │  pods sem    │   │  model_drift_score{version="v2"}         │     │
│  │  padrão      │   │  model_inference_latency_seconds         │     │
│  └──────────────┘   └─────────────────────────────────────────┘     │
│                                        │ scrape /metrics             │
│  ┌──────────────┐   ┌──────────────────▼──────────────────────┐     │
│  │  Fluent Bit  │◀──│         Model Server (FastAPI)           │     │
│  │  (Logging)   │   │                                         │     │
│  │              │   │  POST /predict  → JSON log              │     │
│  │  coleta logs │   │  GET  /metrics  → Prometheus format     │     │
│  │  de predição │   │  GET  /status   → health + métricas     │     │
│  └──────┬───────┘   │  GET  /simulate/degrade → testes        │     │
│         │           └─────────────────────────────────────────┘     │
│         ▼                                                             │
│  ┌──────────────┐   ┌─────────────────────────────────────────┐     │
│  │     Loki     │──▶│              Grafana                     │     │
│  │  (Log Store) │   │  Dashboard de predições em tempo real    │     │
│  └──────────────┘   └─────────────────────────────────────────┘     │
│                                                                       │
│  ┌──────────────┐   ┌─────────────────────────────────────────┐     │
│  │    eBPF      │   │         Argo Workflows                   │     │
│  │  (Kernel     │   │  Pipeline de retraining automático       │     │
│  │  Tracer)     │   │  collect → train → evaluate → promote    │     │
│  └──────────────┘   └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘


Stack de Tecnologias

ComponenteTecnologiaVersãoPapelEntrega contínuaArgo CDstableGitOps — sincroniza Git → clusterCanaryArgo Rolloutsv4.0.6Divide tráfego e avalia métricasRetrainingArgo Workflowsv4.0.6Pipeline automatizado de treinoMétricasPrometheuscommunityColeta AUC, drift, latênciaLoggingFluent Bit5.0.7Coleta logs de predição JSONLog StoreLoki3.6.7Armazena e indexa logsDashboardsGrafanalatestVisualização de prediçõesGovernançaKyvernolatestPolicies de segurança e padrãoObservabilidadeeBPF / bpftracekernel 6.17Syscall tracer sem instrumentaçãoModel serverFastAPI + uvicorn0.110.0Serve predições e expõe métricasCluster localkindv1.31.0Kubernetes em Docker


Versões Implementadas

v0.1 — Fundação GitOps + Canary

Rollout com estratégia canary, dois Services (stable/canary), namespace ml-production, e sincronização automática via Argo CD apontando para github.com/sereno4/ml-gitops.

v0.2 — Observabilidade de Logs

Fluent Bit coleta logs JSON de predição dos pods, filtra por "event":"prediction", e envia para Loki. Grafana exibe cada predição em tempo real com auc_roc, drift_score, latency_ms, input e output.

Query no Grafana:

logql{namespace="ml-production"} | json | line_format "{{.log}}"

v0.3 — Retraining Automático

Argo Workflows executa pipeline de 4 steps em sequência com volume compartilhado entre steps:

collect-data → train-model → evaluate-model → decide-promote

O step decide aprova se AUC >= 0.78 e drift <= 0.20, rejeita caso contrário com exit(1). Em produção o step de promoção faria git commit no rollout.yaml com a nova tag, disparando o canary via Argo CD.

v0.4 — eBPF Kernel Tracer

Rastreia syscalls do model server (uvicorn) em tempo real sem modificar o código ou redesployar:

epoll_wait:  801 calls  ← event loop (saudável)
getpid:      831 calls  ← overhead do prometheus_client (bug descoberto)
recvfrom:    122 calls  ← recebendo requests HTTP
sendto:       96 calls  ← enviando respostas
futex:       117 calls  ← locks do asyncio

O getpid com 831 calls foi um bug real descoberto via eBPF — o prometheus_client do Python chama os.getpid() em todo scrape para nomear workers. Impossível de detectar com APMs tradicionais.


Decisões Técnicas

Por que Rollout e não Deployment?

O Deployment nativo só faz rolling update sem análise. O Rollout pausa entre fases, consulta o Prometheus, e faz rollback automático se as métricas não passarem. Um modelo pode estar com CPU e memória normais mas degradando silenciosamente em AUC — o Deployment não detecta isso, o Rollout sim.

Por que métricas de negócio e não só infraestrutura?

Três métricas monitoradas pelo AnalysisTemplate:

MétricaThresholdMotivomodel_auc_roc≥ 0.75Capacidade discriminativa mínimamodel_drift_score≤ 0.30Distribuição de entrada estávelmodel_inference_latency_seconds P99< 500msSLA de resposta

Por que Kyverno e não OPA/Gatekeeper?

Kyverno usa YAML nativo do Kubernetes — sem Rego. Para um time de ML que já lida com YAML de manifestos, a curva de aprendizado é zero. As policies implementadas garantem que nenhum pod sobe em ml-production sem anotações do Prometheus, resource limits, label team, e tag de imagem explícita.

Por que eBPF e não APM tradicional?

Com APMs tradicionais você vê o que o desenvolvedor decidiu instrumentar. Com eBPF você vê tudo que acontece no kernel — sem tocar no código, sem redesployar, com overhead mínimo. O tracer roda no kernel, não no userspace. Descobrimos o bug do getpid com 10 linhas de bpftrace em 15 segundos.

Por que o model server loga no stdout?

Padrão 12-factor app — o container não sabe para onde os logs vão. O Fluent Bit decide o destino. Hoje vai para Loki; amanhã vai para S3, Kafka ou Elasticsearch sem mudar uma linha do model server.


Estrutura do Repositório

ml-gitops/
├── models/
│   └── recommendation/
│       ├── namespace.yaml           # Namespace ml-production
│       ├── rollout.yaml             # Argo Rollout com estratégia canary
│       ├── services.yaml            # Services stable e canary
│       └── analysis-template.yaml  # Queries Prometheus para validação
├── policies/
│   ├── require-prometheus-annotations.yaml
│   ├── require-resource-limits.yaml
│   └── disallow-latest-tag.yaml
├── logging/
│   └── fluent-bit-configmap.yaml   # Pipeline Fluent Bit → Loki
├── workflows/
│   ├── workflow-template.yaml      # Pipeline de retraining (4 steps)
│   ├── retrain-script.py           # Script de treino
│   └── drift-alert-rule.yaml       # Regras de alerta do Prometheus
├── ebpf/
│   ├── ml-tracer.bt                # Tracer de syscalls do model server
│   ├── inference-latency.bt        # Tracer de latência de inferência
│   └── run-ebpf-monitor.sh         # Script de monitoramento
├── applications/
│   ├── argocd-project.yaml         # AppProject ml-platform
│   └── argocd-app.yaml             # Application → github.com/sereno4/ml-gitops
└── model-server/
    ├── main_v1.py                  # Model server v1 (stable)
    ├── main_v2.py                  # Model server v2 com JSON logging
    ├── Dockerfile.v1
    ├── Dockerfile.v2
    └── Dockerfile.retrain          # Imagem para o pipeline de retraining


Instalação Rápida

Pré-requisitos

bashkubectl version --client   # >= 1.28
kind version               # >= 0.20
helm version               # >= 3.12
docker --version           # >= 24.0
kubectl argo rollouts version
bpftrace --version         # >= 0.16 (para v0.4)

1. Cluster

bashkind create cluster --name ml-canary

2. Argo Rollouts

bashkubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

3. Prometheus

bashhelm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/prometheus \
  --namespace monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set prometheus-pushgateway.enabled=false

4. Loki + Grafana

bashhelm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki-stack \
  --namespace observability --create-namespace \
  --set loki.enabled=true \
  --set promtail.enabled=false \
  --set grafana.enabled=false

helm install grafana grafana/grafana \
  --namespace observability \
  --set adminPassword=admin123 \
  --set datasources."datasources\.yaml".apiVersion=1 \
  --set datasources."datasources\.yaml".datasources[0].name=Loki \
  --set datasources."datasources\.yaml".datasources[0].type=loki \
  --set datasources."datasources\.yaml".datasources[0].url="http://loki.observability.svc.cluster.local:3100" \
  --set datasources."datasources\.yaml".datasources[0].access=proxy \
  --set datasources."datasources\.yaml".datasources[0].isDefault=true

5. Fluent Bit

bashhelm repo add fluent https://fluent.github.io/helm-charts
helm install fluent-bit fluent/fluent-bit \
  --namespace logging --create-namespace \
  --values logging/fluent-bit-values.yaml

6. Kyverno

bashhelm repo add kyverno https://kyverno.github.io/kyverno/
helm install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.enabled=false \
  --set cleanupController.enabled=false \
  --set reportsController.enabled=false

7. Argo CD

bashkubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

8. Argo Workflows

bashhelm install argo-workflows argo/argo-workflows \
  --namespace argo --create-namespace \
  --set controller.replicas=1

9. Build e deploy

bashcd model-server
docker build -f Dockerfile.v1 -t recommendation-model:v1 .
docker build -f Dockerfile.v2 -t recommendation-model:v2 .
docker build -f Dockerfile.retrain -t retrain-model:v1 .
kind load docker-image recommendation-model:v1 --name ml-canary
kind load docker-image recommendation-model:v2 --name ml-canary
kind load docker-image retrain-model:v1 --name ml-canary
cd ..
kubectl apply -f models/recommendation/
kubectl apply -f policies/
kubectl apply -f workflows/workflow-template.yaml


Como Testar

Canary com análise automática

bash# Dispara canary v1 → v2
kubectl argo rollouts set image recommendation-model \
  model-server=recommendation-model:v2 -n ml-production

# Observa em tempo real
kubectl argo rollouts get rollout recommendation-model \
  -n ml-production --watch

Simular degradação e rollback

bash# Terminal 1 — observa
kubectl argo rollouts get rollout recommendation-model \
  -n ml-production --watch

# Terminal 2 — degrada o canary
kubectl port-forward -n ml-production svc/recommendation-model-canary 8082:80 &
curl http://localhost:8082/simulate/degrade
# → {"healthy": false, "auc_roc": 0.55, "drift_score": 0.85}

Retraining manual

bashcat > /tmp/retrain.yaml << 'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: retraining-manual-
  namespace: argo
spec:
  workflowTemplateRef:
    name: ml-retraining-pipeline
EOF
kubectl create -f /tmp/retrain.yaml
kubectl get workflow -n argo --watch

eBPF tracer

bash# Gera tráfego em background
kubectl port-forward -n ml-production svc/recommendation-model-stable 8080:80 &
for i in $(seq 1 50); do
  curl -s -X POST http://localhost:8080/predict \
    -H "Content-Type: application/json" \
    -d '{"features": [0.1, 0.5, 0.3, 0.8, 0.2]}' > /dev/null
done &

# Rastreia syscalls do model server
sudo timeout 15 bpftrace ebpf/ml-tracer.bt

Verificar policies do Kyverno

bash# Deve ser BLOQUEADO — sem anotações Prometheus
kubectl run test --image=nginx -n ml-production

# Deve ser BLOQUEADO — tag :latest
kubectl run test --image=nginx:latest -n ml-production

Ver logs no Grafana

bashkubectl port-forward -n observability svc/grafana 3000:80 --address 0.0.0.0 &
# Acessa http://IP:3000 → Explore → Loki → {namespace="ml-production"}


O que o eBPF Revelou

Rastreando o model server com bpftrace em 15 segundos, sem tocar no código:

epoll_wait:  801 calls  ← event loop aguardando conexões (saudável)
getpid:      831 calls  ← BUG: prometheus_client chama os.getpid() excessivamente
recvfrom:    122 calls  ← recebendo requests HTTP
futex:       117 calls  ← locks do asyncio interno
sendto:       96 calls  ← enviando respostas HTTP
accept4:      48 calls  ← aceitando conexões TCP (1:1 com requests)

O getpid com 831 calls em 10 segundos é overhead real — o prometheus_client do Python chama os.getpid() em todo scrape de métrica para nomear workers. Em produção com alta carga isso se torna mensurável. Descoberto com eBPF, impossível de ver com APMs tradicionais.


Limitações Conhecidas

Rollback por degradação real de AUC — o rollback automático observado foi por NaN (canary sem dados no Prometheus ainda), não por AUC < 0.75. O AnalysisTemplate precisa de inconclusiveLimit: 3 para tolerar os primeiros scrapes sem dados antes de avaliar.

Imagens locais — o model server usa imagePullPolicy: Never com imagens carregadas via kind load. Em produção usaria um registry (ECR, GCR, Harbor).

Retraining simulado — o script de treino usa random para simular métricas. Em produção usaria scikit-learn com dados reais do S3 e o step de promoção faria git commit automaticamente.

Loki sem persistência — configurado com filesystem storage sem PVC persistente. Em produção usaria S3 ou GCS como backend.


Roadmap

v0.1 ✅  Canary + Prometheus + Kyverno + Fluent Bit + Argo CD
v0.2 ✅  Loki + Grafana — logs de predição em tempo real
v0.3 ✅  Retraining automático com Argo Workflows
v0.4 ✅  eBPF — syscall tracer do model server

v0.5     eBPF Security Monitor — detecta exfiltração de dados por modelos comprometidos
v0.6     eBPF Performance Profiler — flamegraphs automáticos quando P99 passa do threshold
v0.7     eBPF Network Policy Enforcer — políticas de rede no nível do kernel
v0.8     Loki queries para detecção de drift em logs históricos


Referências


Argo Rollouts — Analysis & Progressive Delivery
Kyverno Policies
Fluent Bit — Loki Output
bpftrace Reference Guide
Prometheus — Instrumentation Best Practices
Loki — LogQL Query Language



Autor

Daniel — @sereno4


Stack real, problemas reais, soluções reais.
Construído sessão por sessão, debugado linha por linha.
