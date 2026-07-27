// Command gateway starts the Arcanum WhatsApp API HTTP server.
package main

import (
	"log"
	"net/http"
	"os"
	"strconv"

	"github.com/rafaeldourado9/arcanum/internal/api"
	"github.com/rafaeldourado9/arcanum/internal/config"
	"github.com/rafaeldourado9/arcanum/internal/instance"
)

func main() {
	cfg := config.Load()

	if err := os.MkdirAll(cfg.DBPath, 0o755); err != nil {
		log.Fatalf("failed to create GATEWAY_DB_PATH %q: %v", cfg.DBPath, err)
	}

	mgr := instance.NewManager(cfg)
	mgr.RestoreAll()
	server := api.NewServer(mgr, cfg)

	addr := ":" + strconv.Itoa(cfg.Port)
	log.Printf("arcanum gateway listening on %s (db_path=%s)", addr, cfg.DBPath)
	if err := http.ListenAndServe(addr, server); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
