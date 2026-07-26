terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# ─── SSH Key Pair ─────────────────────────────────────────────────────────────

resource "tls_private_key" "vms" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "vms" {
  key_name   = "${var.project}-key"
  public_key = tls_private_key.vms.public_key_openssh
}

resource "local_sensitive_file" "private_key" {
  content         = tls_private_key.vms.private_key_pem
  filename        = "${path.module}/vms-dev.pem"
  file_permission = "0600"
}

# ─── Security Group ───────────────────────────────────────────────────────────

resource "aws_security_group" "vms" {
  name        = "${var.project}-sg"
  description = "VMS Dev - portas necessarias"

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "SSH"
  }

  # HTTP — frontend + webhooks de câmeras + /hik_pro_connect
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP"
  }

  # HTTPS
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS"
  }

  # RTMP — câmeras push (tipo Intelbras, encoders)
  ingress {
    from_port   = 1935
    to_port     = 1935
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "RTMP push cameras"
  }

  # RTSP — visualização e pull de câmeras
  ingress {
    from_port   = 8554
    to_port     = 8554
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "RTSP"
  }

  # RabbitMQ Management UI (só dev)
  ingress {
    from_port   = 15672
    to_port     = 15672
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "RabbitMQ UI (dev)"
  }

  # Saída irrestrita
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-sg" }
}

# ─── AMI — Ubuntu 22.04 LTS (Canonical) ──────────────────────────────────────

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ─── EC2 Instance ─────────────────────────────────────────────────────────────

resource "aws_instance" "vms" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t2.micro" # free tier — 1 vCPU, 1 GB RAM
  key_name               = aws_key_pair.vms.key_name
  vpc_security_group_ids = [aws_security_group.vms.id]

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20  # GB — free tier tem 30 GB
    delete_on_termination = true
  }

  user_data                   = file("${path.module}/user_data.sh")
  user_data_replace_on_change = true

  tags = { Name = "${var.project}" }
}

# ─── Elastic IP (IP fixo para as câmeras apontarem) ──────────────────────────

resource "aws_eip" "vms" {
  instance = aws_instance.vms.id
  domain   = "vpc"

  tags = { Name = "${var.project}-eip" }
}
