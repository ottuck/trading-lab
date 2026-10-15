# Lightsail 시드니 서버 1대 (project.md 6절. 계정 제약으로 서울 대신 시드니, 2026-10-08). 비용이 드는 리소스이므로 apply 전에 plan을 확인한다.
#   cd infra/lightsail && terraform init && terraform plan && terraform apply
# AWS 자격 증명은 aws login(임시 자격 증명)·프로필·환경변수 중 하나로 제공하고 저장소에 넣지 않는다.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "ap-southeast-2"
}

variable "availability_zone" {
  type    = string
  default = "ap-southeast-2a"
}

variable "bundle_id" {
  type        = string
  default     = "small_3_2"
  description = "2GB RAM 플랜. 확인: aws lightsail get-bundles --region ap-southeast-2"
}

variable "blueprint_id" {
  type    = string
  default = "ubuntu_24_04"
}

variable "name" {
  type    = string
  default = "quant-lab-02"
}

resource "aws_lightsail_instance" "server" {
  name              = var.name
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id

  # 매일 자동 스냅샷 (UTC 18:00 = KST 03:00, 정기 평가 시각과 겹치지 않음)
  add_on {
    type          = "AutoSnapshot"
    snapshot_time = "18:00"
    status        = "Enabled"
  }

  # 이름은 Lightsail에서 바꿀 수 없어 태그로 용도를 적는다 (Trading Lab·ur-check·puny-chat이 함께 쓴다)
  tags = {
    project = "quant-lab"
    purpose = "shared"
  }
}

# 토스 허용 IP에 등록할 고정 송신 IP
resource "aws_lightsail_static_ip" "server" {
  name = "${var.name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "server" {
  static_ip_name = aws_lightsail_static_ip.server.name
  instance_name  = aws_lightsail_instance.server.name
}

# 인바운드는 Lightsail 콘솔의 브라우저 SSH만 허용한다.
# 화면은 Cloudflare Tunnel·Access, 관리 SSH는 Tailscale을 쓴다. 둘 다 공개 인바운드 포트가 필요 없다.
resource "aws_lightsail_instance_public_ports" "server" {
  instance_name = aws_lightsail_instance.server.name

  port_info {
    protocol          = "tcp"
    from_port         = 22
    to_port           = 22
    cidr_list_aliases = ["lightsail-connect"]
  }
}

output "static_ip" {
  description = "토스 WTS > Open API > 허용 IP에 추가할 주소"
  value       = aws_lightsail_static_ip.server.ip_address
}

output "next_step" {
  value = "Lightsail 콘솔에서 ${var.name} 인스턴스의 '브라우저 SSH'로 접속해 project.md 6절 절차를 진행"
}
