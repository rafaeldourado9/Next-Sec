package api

import (
	"encoding/json"
	"net/http"

	"github.com/rafaeldourado9/arcanum/internal/instance"
)

type markReadReq struct {
	ReadMessages []struct {
		RemoteJid string `json:"remoteJid"`
		ID        string `json:"id"`
	} `json:"readMessages"`
}

func handleMarkAsRead(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req markReadReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.ReadMessages) == 0 {
			writeJSON(w, 400, map[string]string{"error": "Missing 'readMessages'"})
			return
		}

		for _, m := range req.ReadMessages {
			_ = inst.Provider.MarkAsRead(m.ID, m.RemoteJid)
		}

		writeJSON(w, 200, map[string]any{"ok": true, "read": len(req.ReadMessages)})
	}
}

type checkNumbersReq struct {
	Numbers []string `json:"numbers"`
}

func handleCheckNumbers(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req checkNumbersReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.Numbers) == 0 {
			writeJSON(w, 400, map[string]string{"error": "Missing 'numbers'"})
			return
		}

		results, err := inst.Provider.CheckNumbers(req.Numbers)
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, results)
	}
}

type updateProfileNameReq struct {
	Name string `json:"name"`
}

func handleUpdateProfileName(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req updateProfileNameReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Name == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'name'"})
			return
		}

		if err := inst.Provider.UpdateProfileName(req.Name); err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "name": req.Name})
	}
}

type updateProfileStatusReq struct {
	Status string `json:"status"`
}

func handleUpdateProfileStatus(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req updateProfileStatusReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Status == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'status'"})
			return
		}

		if err := inst.Provider.UpdateProfileStatus(req.Status); err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "status": req.Status})
	}
}

// Stubs for findChats, findContacts, findMessages — these require message store
func handleFindChats(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"chats": []any{}, "note": "Chat history requires message store — coming soon"})
	}
}

func handleFindContacts(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"contacts": []any{}, "note": "Contact store — coming soon"})
	}
}

func handleFindMessages(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}
		writeJSON(w, 200, map[string]any{"messages": []any{}, "note": "Message store — coming soon"})
	}
}

func handleArchiveChat(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req struct {
			Chat    string `json:"chat"`
			Archive bool   `json:"archive"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Chat == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'chat'"})
			return
		}

		// whatsmeow doesn't expose archive directly — placeholder
		writeJSON(w, 200, map[string]any{"ok": true, "chat": req.Chat, "archived": req.Archive})
	}
}

func handleUpdateProfilePicture(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req struct {
			Picture string `json:"picture"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Picture == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'picture'"})
			return
		}

		if err := inst.Provider.UpdateProfilePicture(req.Picture); err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true})
	}
}
