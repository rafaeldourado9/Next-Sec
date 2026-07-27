package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/rafaeldourado9/arcanum/internal/instance"
	"github.com/rafaeldourado9/arcanum/internal/webhook"
)

func handleGetWebhook(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := chi.URLParam(r, "instance")
		inst, err := mgr.Get(name)
		if err != nil {
			writeJSON(w, 404, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, inst.WebhookConfig)
	}
}

type setWebhookReq struct {
	URL     string   `json:"url"`
	Events  []string `json:"events"`
	Enabled *bool    `json:"enabled"`
}

func handleSetWebhook(mgr *instance.Manager, secret string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := chi.URLParam(r, "instance")
		inst, err := mgr.Get(name)
		if err != nil {
			writeJSON(w, 404, map[string]string{"error": err.Error()})
			return
		}

		var req setWebhookReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, 400, map[string]string{"error": "Invalid JSON"})
			return
		}

		if req.URL != "" {
			inst.WebhookConfig.URL = req.URL
			inst.Webhook = webhook.NewForwarder(req.URL, "simple", secret)
		}
		if len(req.Events) > 0 {
			inst.WebhookConfig.Events = req.Events
		}
		if req.Enabled != nil {
			inst.WebhookConfig.Enabled = *req.Enabled
		}

		writeJSON(w, 200, inst.WebhookConfig)
	}
}
