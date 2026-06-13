#!/bin/bash
# Roda o tracer eBPF enquanto gera tráfego no model server
# Uso: ./run-ebpf-monitor.sh

set -e

echo "=== ML eBPF Monitor ==="
echo ""

# Port-forward em background
echo "[1] Iniciando port-forward para o model server..."
kubectl port-forward -n ml-production svc/recommendation-model-stable 8080:80 &
PF_PID=$!
sleep 2

# Gera tráfego em background
echo "[2] Gerando tráfego contínuo..."
(
  for i in $(seq 1 50); do
    curl -s -X POST http://localhost:8080/predict \
      -H "Content-Type: application/json" \
      -d '{"features": [0.1, 0.5, 0.3, 0.8, 0.2]}' > /dev/null
    sleep 0.5
  done
) &
TRAFFIC_PID=$!

# Roda o tracer por 15 segundos
echo "[3] Iniciando tracer eBPF (15 segundos)..."
echo ""
sudo timeout 15 bpftrace /home/daniel-dev/ml-gitops/ebpf/ml-tracer.bt || true

# Limpa
echo ""
echo "[4] Limpando..."
kill $PF_PID $TRAFFIC_PID 2>/dev/null || true

echo "=== Concluído ==="
