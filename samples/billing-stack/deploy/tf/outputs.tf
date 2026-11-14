output "workers" {
  description = "Running worker container endpoints"
  value = [
    for c in docker_container.worker : {
      name         = c.name
      container_id = substr(c.id, 0, 12)
      port         = c.ports[0].external
      url          = "http://127.0.0.1:${c.ports[0].external}"
    }
  ]
}
