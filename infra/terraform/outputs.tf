output "public_ip" {
  description = "IP público fixo (Elastic IP) — configure nas câmeras"
  value       = aws_eip.vms.public_ip
}

output "ssh_command" {
  description = "Comando SSH para acessar o servidor"
  value       = "ssh -i infra/terraform/vms-dev.pem ubuntu@${aws_eip.vms.public_ip}"
}

output "app_url" {
  description = "URL do frontend"
  value       = "http://${aws_eip.vms.public_ip}"
}

output "webhook_hikvision" {
  description = "URL para configurar no Alarm Server da Hikvision"
  value       = "http://${aws_eip.vms.public_ip}/hik_pro_connect?camera_id=<uuid>"
}

output "webhook_intelbras" {
  description = "URL para configurar no DVR/NVR Intelbras"
  value       = "http://${aws_eip.vms.public_ip}/intelbras_events?camera_id=<uuid>"
}

output "rtmp_url" {
  description = "URL RTMP para câmeras push"
  value       = "rtmp://${aws_eip.vms.public_ip}:1935/live/<stream_key>"
}

output "rabbitmq_ui" {
  description = "RabbitMQ Management UI"
  value       = "http://${aws_eip.vms.public_ip}:15672"
}
