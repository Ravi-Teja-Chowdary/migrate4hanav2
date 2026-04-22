#!/bin/bash
set -e
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
# Configure Ollama to listen on all interfaces
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
EOF
systemctl daemon-reload
systemctl enable ollama
systemctl start ollama
# Pull the model (runs in background; may take 15-30 min for 27B)
sleep 10
ollama pull ${ollama_model} &
