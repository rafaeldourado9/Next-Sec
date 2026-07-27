package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/rafaeldourado9/arcanum/internal/config"
	"github.com/rafaeldourado9/arcanum/internal/instance"
)

func NewServer(mgr *instance.Manager, cfg *config.Config) http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.Recoverer)
	r.Use(middleware.RealIP)

	// System
	r.Get("/health", handleHealthMulti(mgr))
	r.Get("/docs", handleDocs())
	r.Get("/docs/openapi.json", handleOpenAPI())

	// Instance
	r.Post("/api/instance/create", handleCreateInstance(mgr))
	r.Get("/api/instance/connect/{instance}", handleConnectInstance(mgr))
	r.Get("/api/instance/connectionState/{instance}", handleConnectionState(mgr))
	r.Delete("/api/instance/logout/{instance}", handleLogoutInstance(mgr))
	r.Delete("/api/instance/delete/{instance}", handleDeleteInstance(mgr))
	r.Post("/api/instance/restart/{instance}", handleRestartInstance(mgr))
	r.Post("/api/instance/setPresence/{instance}", handleSetPresence(mgr))
	r.Get("/api/instance/fetchInstances", handleFetchInstances(mgr))
	r.Get("/api/instance/qr/{instance}", handleGetQR(mgr))
	r.Post("/api/instance/pair/{instance}", handlePairInstance(mgr))

	// Message
	r.Post("/api/message/sendText/{instance}", handleSendText(mgr, cfg))
	r.Post("/api/message/sendMedia/{instance}", handleSendMedia(mgr, cfg))
	r.Post("/api/message/sendLocation/{instance}", handleSendLocation(mgr))
	r.Post("/api/message/sendContact/{instance}", handleSendContact(mgr))
	r.Post("/api/message/sendReaction/{instance}", handleSendReaction(mgr))
	r.Post("/api/message/sendPoll/{instance}", handleSendPoll(mgr))

	// Chat
	r.Post("/api/chat/archiveChat/{instance}", handleArchiveChat(mgr))
	r.Post("/api/chat/findChats/{instance}", handleFindChats(mgr))
	r.Post("/api/chat/findContacts/{instance}", handleFindContacts(mgr))
	r.Post("/api/chat/findMessages/{instance}", handleFindMessages(mgr))
	r.Post("/api/chat/markMessageAsRead/{instance}", handleMarkAsRead(mgr))
	r.Post("/api/chat/updateProfileName/{instance}", handleUpdateProfileName(mgr))
	r.Post("/api/chat/updateProfilePicture/{instance}", handleUpdateProfilePicture(mgr))
	r.Post("/api/chat/updateProfileStatus/{instance}", handleUpdateProfileStatus(mgr))
	r.Post("/api/chat/checkWhatsAppNumbers/{instance}", handleCheckNumbers(mgr))

	// Events
	r.Get("/api/events/webhook/{instance}", handleGetWebhook(mgr))
	r.Post("/api/events/webhook/{instance}", handleSetWebhook(mgr, cfg.WebhookSecret))

	// Settings
	r.Get("/api/settings/{instance}", handleGetSettings(mgr))
	r.Post("/api/settings/{instance}", handleSetSettings(mgr))

	return r
}

func handleHealthMulti(mgr *instance.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		instances := mgr.List()
		writeJSON(w, 200, map[string]any{
			"status":    "ok",
			"instances": len(instances),
		})
	}
}
