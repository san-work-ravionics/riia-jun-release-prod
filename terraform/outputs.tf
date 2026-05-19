output "public_ip" {
  description = "The public Internet IP of the RITA platform"
  value       = aws_eip.rita.public_ip
}

output "ssh_command" {
  description = "Command to neatly SSH into the server to manage K3s"
  value       = "ssh -i generated-key.pem ubuntu@${aws_eip.rita.public_ip}"
}
