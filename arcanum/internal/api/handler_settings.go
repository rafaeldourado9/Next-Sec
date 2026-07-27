package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/rafaeldourado9/arcanum/internal/instance"
)

func handleGetSettings(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := chi.URLParam(r, "instance")
		inst, err := mgr.Get(name)
		if err != nil {
			writeJSON(w, 404, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, inst.Settings)
	}
}

func handleSetSettings(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := chi.URLParam(r, "instance")
		inst, err := mgr.Get(name)
		if err != nil {
			writeJSON(w, 404, map[string]string{"error": err.Error()})
			return
		}

		if err := json.NewDecoder(r.Body).Decode(inst.Settings); err != nil {
			writeJSON(w, 400, map[string]string{"error": "Invalid JSON"})
			return
		}

		writeJSON(w, 200, inst.Settings)
	}
}
