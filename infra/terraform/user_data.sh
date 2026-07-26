#!/bin/bash
# Bootstrap EC2 — VMS Dev Server
# Ubuntu 22.04 LTS / t2.micro (1 vCPU, 1 GB RAM)
set -euo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a /var/log/vms-bootstrap.log; }

log "=== VMS Bootstrap iniciado ==="

# ─── Swap (crítico — t2.micro tem só 1 GB RAM) ───────────────────────────────
log "Configurando swap de 2 GB..."
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Kernel tuning para baixo RAM
cat >> /etc/sysctl.conf << 'EOF'
vm.swappiness=20
vm.overcommit_memory=1
net.core.somaxconn=1024
EOF
sysctl -p

# ─── Pacotes base ─────────────────────────────────────────────────────────────
log "Instalando pacotes base..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q \
  curl git make rsync \
  ca-certificates gnupg lsb-release \
  htop ncdu jq unzip

# ─── Docker CE ────────────────────────────────────────────────────────────────
log "Instalando Docker CE..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Adiciona ubuntu ao grupo docker
usermod -aG docker ubuntu

# Configura daemon do Docker com log rotation e limites de memória
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 65536,
      "Soft": 65536
    }
  }
}
EOF

systemctl enable docker
systemctl start docker

# ─── Diretório do projeto ─────────────────────────────────────────────────────
log "Criando diretório /opt/vms..."
mkdir -p /opt/vms
chown ubuntu:ubuntu /opt/vms

# ─── Systemd service — auto-start na reinicialização ─────────────────────────
cat > /etc/systemd/system/vms.service << 'EOF'
[Unit]
Description=VMS Stack
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/vms
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose up -d --remove-orphans
User=ubuntu
Group=ubuntu
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vms

# ─── Aliases úteis ────────────────────────────────────────────────────────────
cat >> /home/ubuntu/.bashrc << 'EOF'

# VMS aliases
alias vms='cd /opt/vms'
alias vlogs='cd /opt/vms && docker compose logs -f'
alias vup='cd /opt/vms && docker compose up -d'
alias vdown='cd /opt/vms && docker compose down'
alias vps='cd /opt/vms && docker compose ps'
alias vrestart='cd /opt/vms && docker compose restart'
alias vbuild='cd /opt/vms && docker compose up -d --build'
EOF

log "=== Bootstrap concluído! Aguardando deploy... ==="
log "O servidor está pronto. Execute ./deploy.sh para enviar o código."
