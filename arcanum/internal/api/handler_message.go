package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/rafaeldourado9/arcanum/internal/antiban"
	"github.com/rafaeldourado9/arcanum/internal/config"
	"github.com/rafaeldourado9/arcanum/internal/instance"
	"github.com/rafaeldourado9/arcanum/internal/media"
	"github.com/rafaeldourado9/arcanum/internal/provider"
)

func requireConnected(mgr *instance.Manager, r *http.Request, w http.ResponseWriter) (*instance.Instance, bool) {
	name := chi.URLParam(r, "instance")
	inst, err := mgr.Get(name)
	if err != nil {
		writeJSON(w, 404, map[string]string{"error": err.Error()})
		return nil, false
	}
	if inst.Provider.Status() != provider.StatusConnected {
		writeJSON(w, 503, map[string]any{"error": "not connected", "status": inst.Provider.Status()})
		return nil, false
	}
	if !inst.Limiter.Allow() {
		cur, lim := inst.Limiter.Usage()
		writeJSON(w, 429, map[string]any{"error": "rate limit exceeded", "current": cur, "limit": lim})
		return nil, false
	}
	return inst, true
}

type sendTextReq struct {
	Number string `json:"number"`
	Text   string `json:"text"`
}

func handleSendText(mgr *instance.Manager, cfg *config.Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendTextReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Number == "" || req.Text == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'number' and/or 'text'"})
			return
		}

		// The anti-ban delay (pre-delay + typing simulation) can take up to ~13s by
		// design — it paces what WhatsApp sees, it's not part of the caller's HTTP
		// contract. Acknowledge immediately and run the humanized send in the
		// background so callers never need a long timeout to get a reply queued.
		go func() {
			antiban.HumanizedSend(inst.Provider, req.Number, req.Text, cfg)
			sendWithRetry(req.Number, func() error {
				_, err := inst.Provider.SendText(provider.SendTextOptions{To: req.Number, Text: req.Text})
				return err
			})
		}()

		writeJSON(w, 202, map[string]any{"ok": true, "status": "queued"})
	}
}

type sendMediaReq struct {
	Number    string `json:"number"`
	MediaType string `json:"mediatype"`
	MimeType  string `json:"mimetype"`
	Caption   string `json:"caption"`
	Media     string `json:"media"`
	FileName  string `json:"fileName"`
}

func handleSendMedia(mgr *instance.Manager, cfg *config.Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendMediaReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Number == "" || req.Media == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'number' and/or 'media'"})
			return
		}
		if req.MediaType == "" {
			req.MediaType = "document"
		}

		presenceType := "composing"
		if req.MediaType == "audio" {
			presenceType = "recording"
		}
		_ = inst.Provider.SendPresence(req.Number, presenceType)

		data, err := media.FromBase64(req.Media)
		if err != nil {
			data = nil
		}

		opts := provider.SendMediaOptions{
			To:       req.Number,
			Type:     req.MediaType,
			Data:     data,
			MimeType: req.MimeType,
			Filename: req.FileName,
			Caption:  req.Caption,
		}
		if data == nil {
			opts.URL = req.Media
		}

		result, sendErr := inst.Provider.SendMedia(opts)
		_ = inst.Provider.SendPresence(req.Number, "paused")

		if sendErr != nil {
			writeJSON(w, 500, map[string]string{"error": sendErr.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "messageId": result.MessageID, "provider": result.Provider})
	}
}

type sendLocationReq struct {
	Number    string  `json:"number"`
	Name      string  `json:"name"`
	Address   string  `json:"address"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}

func handleSendLocation(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendLocationReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Number == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'number'"})
			return
		}

		result, err := inst.Provider.SendLocation(provider.SendLocationOptions{
			To:        req.Number,
			Latitude:  req.Latitude,
			Longitude: req.Longitude,
			Name:      req.Name,
			Address:   req.Address,
		})
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "messageId": result.MessageID, "provider": result.Provider})
	}
}

type contactEntry struct {
	FullName    string `json:"fullName"`
	PhoneNumber string `json:"phoneNumber"`
}

type sendContactReq struct {
	Number  string         `json:"number"`
	Contact []contactEntry `json:"contact"`
}

func handleSendContact(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendContactReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Number == "" || len(req.Contact) == 0 {
			writeJSON(w, 400, map[string]string{"error": "Missing 'number' and/or 'contact'"})
			return
		}

		contacts := make([]provider.ContactCard, len(req.Contact))
		for i, c := range req.Contact {
			contacts[i] = provider.ContactCard{FullName: c.FullName, PhoneNumber: c.PhoneNumber}
		}

		result, err := inst.Provider.SendContact(provider.SendContactOptions{
			To:       req.Number,
			Contacts: contacts,
		})
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "messageId": result.MessageID, "provider": result.Provider})
	}
}

type reactionKey struct {
	RemoteJid string `json:"remoteJid"`
	ID        string `json:"id"`
}

type sendReactionReq struct {
	Key      reactionKey `json:"key"`
	Reaction string      `json:"reaction"`
}

func handleSendReaction(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendReactionReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Key.ID == "" {
			writeJSON(w, 400, map[string]string{"error": "Missing 'key' and/or 'reaction'"})
			return
		}

		result, err := inst.Provider.SendReaction(provider.SendReactionOptions{
			To:        req.Key.RemoteJid,
			MessageID: req.Key.ID,
			Emoji:     req.Reaction,
		})
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "messageId": result.MessageID, "provider": result.Provider})
	}
}

type sendPollReq struct {
	Number          string   `json:"number"`
	Name            string   `json:"name"`
	SelectableCount int      `json:"selectableCount"`
	Values          []string `json:"values"`
}

func handleSendPoll(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		inst, ok := requireConnected(mgr, r, w)
		if !ok {
			return
		}

		var req sendPollReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Number == "" || req.Name == "" || len(req.Values) == 0 {
			writeJSON(w, 400, map[string]string{"error": "Missing 'number', 'name', or 'values'"})
			return
		}

		if req.SelectableCount == 0 {
			req.SelectableCount = 1
		}

		result, err := inst.Provider.SendPoll(provider.SendPollOptions{
			To:              req.Number,
			Name:            req.Name,
			Options:         req.Values,
			SelectableCount: req.SelectableCount,
		})
		if err != nil {
			writeJSON(w, 500, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, 200, map[string]any{"ok": true, "messageId": result.MessageID, "provider": result.Provider})
	}
}
