package api

var fullOpenAPISpec = map[string]any{
	"openapi": "3.1.0",
	"info": map[string]any{
		"title":       "Arcanum API",
		"description": "Open-source WhatsApp Gateway with anti-ban, multi-instance, and full media support.",
		"version":     "1.0.0",
		"contact": map[string]string{
			"name": "Arcanum API",
			"url":  "https://github.com/rafaeldourado9/arcanum",
		},
		"license": map[string]string{
			"name": "MIT",
			"url":  "https://opensource.org/licenses/MIT",
		},
	},
	"servers": []map[string]string{
		{"url": "http://localhost:3100", "description": "Local"},
	},
	"tags": []map[string]string{
		{"name": "Instance", "description": "Manage WhatsApp instances (connect, disconnect, create, delete)"},
		{"name": "Message", "description": "Send messages (text, media, buttons, lists, location, contact, poll, reaction, template)"},
		{"name": "Chat", "description": "Chat operations (archive, find, mark read, profile updates)"},
		{"name": "Group", "description": "Group management (create, info, participants)"},
		{"name": "Events", "description": "Webhook and WebSocket configuration"},
		{"name": "Settings", "description": "Instance settings and proxy configuration"},
		{"name": "Label", "description": "WhatsApp label management"},
		{"name": "Template", "description": "Message template management"},
		{"name": "Call", "description": "Voice/video call operations"},
		{"name": "Business", "description": "WhatsApp Business catalog and collections"},
		{"name": "System", "description": "Health check and API docs"},
	},
	"paths": buildPaths(),
}

func buildPaths() map[string]any {
	return map[string]any{
		// ── System ──
		"/health": pathGet("System", "Health check", "Returns gateway status"),
		"/api/status": pathGet("System", "Connection status", "Returns connection state and rate limit usage"),

		// ── Instance ──
		"/api/instance/create": pathPost("Instance", "Create instance", "Create a new WhatsApp instance", bodyObj(map[string]any{
			"instanceName": strProp("Name for this instance", "default"),
			"webhook":      strProp("Webhook URL for events", "https://example.com/webhook"),
			"webhookEvents": arrProp("Events to subscribe", []string{"messages", "status", "groups"}),
		})),
		"/api/instance/connect/{instance}": pathGetQR("Instance", "Connect instance", "Connect and get QR code (waits briefly for the code to be ready)"),
		"/api/instance/connectionState/{instance}": pathGetQR("Instance", "Get connection state", "Returns current connection status and QR code if pending"),
		"/api/instance/qr/{instance}": pathGetQR("Instance", "Get QR code", "Returns the current QR code for a pending connection"),
		"/api/instance/logout/{instance}": pathDelParam("Instance", "Logout instance", "Disconnect and clear session", "instance"),
		"/api/instance/delete/{instance}": pathDelParam("Instance", "Delete instance", "Remove instance completely", "instance"),
		"/api/instance/restart/{instance}": pathPostParam("Instance", "Restart instance", "Reconnect instance", "instance"),
		"/api/instance/setPresence/{instance}": pathPost("Instance", "Set presence", "Set online/offline presence", bodyObj(map[string]any{
			"presence": strProp("Presence type", "available"),
		})),
		"/api/instance/pair/{instance}": pathPost("Instance", "Pair by phone number", "Get a pairing code to link via phone number instead of scanning a QR code", bodyObj(map[string]any{
			"phone": strProp("Phone number with country code", "5511999999999"),
		})),
		"/api/instance/fetchInstances": pathGet("Instance", "Fetch all instances", "List all created instances"),

		// ── Message ──
		"/api/message/sendText/{instance}": pathPost("Message", "Send text message", "Send a text message with anti-ban measures (typing indicator, random delay)", bodyObj(map[string]any{
			"number": strProp("Recipient phone number", "5511999999999"),
			"text":   strProp("Message text", "Hello from Arcanum!"),
		})),
		"/api/message/sendMedia/{instance}": pathPost("Message", "Send media message", "Send image, audio, document, or video", bodyObj(map[string]any{
			"number":    strProp("Recipient phone number", "5511999999999"),
			"mediatype": strProp("Media type: image, audio, document, video", "image"),
			"mimetype":  strProp("MIME type", "image/jpeg"),
			"caption":   strProp("Caption for the media", "Check this out"),
			"media":     strProp("Base64 encoded file or URL", "https://example.com/photo.jpg"),
			"fileName":  strProp("Filename for documents", "report.pdf"),
		})),
		"/api/message/sendButtons/{instance}": pathPost("Message", "Send buttons", "Send interactive button message", bodyObj(map[string]any{
			"number":      strProp("Recipient", "5511999999999"),
			"title":       strProp("Button title", "Choose an option"),
			"description": strProp("Description", "Select one of the options below"),
			"buttons":     arrProp("Button list", []string{`{"buttonText": "Option 1"}`, `{"buttonText": "Option 2"}`}),
		})),
		"/api/message/sendList/{instance}": pathPost("Message", "Send list", "Send interactive list message", bodyObj(map[string]any{
			"number":      strProp("Recipient", "5511999999999"),
			"title":       strProp("List title", "Services"),
			"description": strProp("Description", "Select a service"),
			"buttonText":  strProp("Button label", "View options"),
			"sections":    arrProp("List sections", []string{`{"title":"Section 1","rows":[...]}`}),
		})),
		"/api/message/sendLocation/{instance}": pathPost("Message", "Send location", "Send GPS location", bodyObj(map[string]any{
			"number":    strProp("Recipient", "5511999999999"),
			"name":      strProp("Location name", "City Hall"),
			"address":   strProp("Address", "123 Main St"),
			"latitude":  numProp("Latitude", -23.55),
			"longitude": numProp("Longitude", -46.63),
		})),
		"/api/message/sendContact/{instance}": pathPost("Message", "Send contact", "Send a contact card (vCard)", bodyObj(map[string]any{
			"number": strProp("Recipient", "5511999999999"),
			"contact": arrProp("Contacts", []string{`{"fullName":"John","wuid":"5511888888888","phoneNumber":"5511888888888"}`}),
		})),
		"/api/message/sendPoll/{instance}": pathPost("Message", "Send poll", "Send a poll message", bodyObj(map[string]any{
			"number":       strProp("Recipient", "5511999999999"),
			"name":         strProp("Poll question", "Best day for meeting?"),
			"selectableCount": numProp("Max selections", 1),
			"values":       arrProp("Poll options", []string{"Monday", "Tuesday", "Wednesday"}),
		})),
		"/api/message/sendReaction/{instance}": pathPost("Message", "Send reaction", "React to a message with an emoji", bodyObj(map[string]any{
			"key": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"remoteJid": strProp("Chat JID", "5511999999999@s.whatsapp.net"),
					"id":        strProp("Message ID", "ABCDEF123456"),
				},
			},
			"reaction": strProp("Emoji reaction", "👍"),
		})),
		"/api/message/sendTemplate/{instance}": pathPost("Message", "Send template message", "Send a pre-approved template (Meta Business API)", bodyObj(map[string]any{
			"number":   strProp("Recipient", "5511999999999"),
			"name":     strProp("Template name", "hello_world"),
			"language": strProp("Language code", "en_US"),
		})),

		// ── Chat ──
		"/api/chat/archiveChat/{instance}": pathPost("Chat", "Archive chat", "Archive or unarchive a conversation", bodyObj(map[string]any{
			"chat":    strProp("Chat JID", "5511999999999@s.whatsapp.net"),
			"archive": boolProp("Archive (true) or unarchive (false)", true),
		})),
		"/api/chat/findChats/{instance}": pathPost("Chat", "Find chats", "List all chats", nil),
		"/api/chat/findContacts/{instance}": pathPost("Chat", "Find contacts", "List all contacts", nil),
		"/api/chat/findMessages/{instance}": pathPost("Chat", "Find messages", "Search messages in a chat", bodyObj(map[string]any{
			"where": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"key": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"remoteJid": strProp("Chat JID", "5511999999999@s.whatsapp.net"),
						},
					},
				},
			},
			"limit": numProp("Max results", 20),
		})),
		"/api/chat/markMessageAsRead/{instance}": pathPost("Chat", "Mark message as read", "Send read receipt for messages", bodyObj(map[string]any{
			"readMessages": arrProp("Message IDs to mark as read", []string{`{"remoteJid":"...","id":"..."}`}),
		})),
		"/api/chat/updateProfileName/{instance}": pathPost("Chat", "Update profile name", "Change WhatsApp display name", bodyObj(map[string]any{
			"name": strProp("New display name", "Arcanum Bot"),
		})),
		"/api/chat/updateProfilePicture/{instance}": pathPost("Chat", "Update profile picture", "Change WhatsApp profile photo", bodyObj(map[string]any{
			"picture": strProp("Base64 encoded image", "<base64>"),
		})),
		"/api/chat/updateProfileStatus/{instance}": pathPost("Chat", "Update profile status", "Change WhatsApp about/status text", bodyObj(map[string]any{
			"status": strProp("New status text", "Powered by Arcanum API"),
		})),
		"/api/chat/checkWhatsAppNumbers/{instance}": pathPost("Chat", "Check WhatsApp numbers", "Verify which phone numbers have WhatsApp", bodyObj(map[string]any{
			"numbers": arrProp("Phone numbers to check", []string{"5511999999999", "5511888888888"}),
		})),

		// ── Group ──
		"/api/group/create/{instance}": pathPost("Group", "Create group", "Create a new WhatsApp group", bodyObj(map[string]any{
			"subject":      strProp("Group name", "Project Team"),
			"participants": arrProp("Participant phone numbers", []string{"5511999999999", "5511888888888"}),
		})),
		"/api/group/info/{instance}": pathGetParam("Group", "Get group info", "Get group metadata (name, description, participants)", "instance"),
		"/api/group/participants/{instance}": pathGetParam("Group", "Get participants", "List group participants", "instance"),
		"/api/group/updateParticipant/{instance}": pathPost("Group", "Update participant", "Add, remove, promote, or demote a participant", bodyObj(map[string]any{
			"groupJid": strProp("Group JID", "123456789@g.us"),
			"action":   strProp("Action: add, remove, promote, demote", "add"),
			"participants": arrProp("Participant numbers", []string{"5511999999999"}),
		})),

		// ── Events ──
		"/api/events/webhook/{instance}": map[string]any{
			"get": op("Events", "Get webhook", "Get current webhook configuration for this instance"),
			"post": opBody("Events", "Set webhook", "Configure webhook URL and events", bodyObj(map[string]any{
				"url":     strProp("Webhook URL", "https://example.com/webhook"),
				"events":  arrProp("Events to subscribe", []string{"messages", "status", "groups", "calls"}),
				"enabled": boolProp("Enable webhook", true),
			})),
		},
		"/api/events/websocket/{instance}": pathPost("Events", "Set WebSocket", "Enable WebSocket events for real-time streaming", bodyObj(map[string]any{
			"enabled": boolProp("Enable WebSocket", true),
		})),

		// ── Settings ──
		"/api/settings/{instance}": map[string]any{
			"get":  op("Settings", "Get settings", "Get current instance settings"),
			"post": opBody("Settings", "Set settings", "Update instance settings", bodyObj(map[string]any{
				"rejectCalls":       boolProp("Auto-reject incoming calls", false),
				"groupsIgnore":      boolProp("Ignore group messages", false),
				"alwaysOnline":      boolProp("Always show as online", false),
				"readMessages":      boolProp("Auto-read incoming messages", true),
				"readStatus":        boolProp("Auto-read status/stories", false),
				"syncFullHistory":   boolProp("Sync full chat history on connect", false),
			})),
		},

		// ── Proxy ──
		"/api/proxy/{instance}": map[string]any{
			"get": op("Settings", "Get proxy", "Get proxy configuration"),
			"post": opBody("Settings", "Set proxy", "Configure HTTP/SOCKS proxy", bodyObj(map[string]any{
				"enabled":  boolProp("Enable proxy", true),
				"host":     strProp("Proxy host", "proxy.example.com"),
				"port":     numProp("Proxy port", 8080),
				"protocol": strProp("Protocol: http, https, socks5", "socks5"),
				"username": strProp("Proxy username (optional)", ""),
				"password": strProp("Proxy password (optional)", ""),
			})),
		},

		// ── Label ──
		"/api/label/{instance}": map[string]any{
			"get": op("Label", "Get labels", "List all WhatsApp labels"),
			"post": opBody("Label", "Handle label", "Create, update, or assign label to chat", bodyObj(map[string]any{
				"name":   strProp("Label name", "Important"),
				"color":  numProp("Label color index", 1),
				"chatId": strProp("Chat to assign (optional)", "5511999999999@s.whatsapp.net"),
			})),
		},

		// ── Template ──
		"/api/template/create/{instance}": pathPost("Template", "Create template", "Create a message template (Meta Business API)", bodyObj(map[string]any{
			"name":     strProp("Template name", "order_confirmation"),
			"language": strProp("Language", "pt_BR"),
			"category": strProp("Category: MARKETING, UTILITY, AUTHENTICATION", "UTILITY"),
			"components": arrProp("Template components", []string{`{"type":"BODY","text":"Hello {{1}}"}`}),
		})),
		"/api/template/delete/{instance}/{name}": pathDelParam("Template", "Delete template", "Delete a message template", "instance"),
		"/api/template/edit/{instance}": pathPost("Template", "Edit template", "Edit an existing template", bodyObj(map[string]any{
			"name":       strProp("Template name", "order_confirmation"),
			"components": arrProp("Updated components", []string{`{"type":"BODY","text":"Updated {{1}}"}`}),
		})),
		"/api/template/find/{instance}": pathGetParam("Template", "Find templates", "List all approved templates", "instance"),

		// ── Call ──
		"/api/call/offer/{instance}": pathPost("Call", "Offer call", "Initiate a voice/video call", bodyObj(map[string]any{
			"number":   strProp("Recipient", "5511999999999"),
			"callType": strProp("Type: audio, video", "audio"),
		})),

		// ── Business ──
		"/api/business/catalog/{instance}": pathPost("Business", "Get catalog", "Fetch WhatsApp Business catalog", nil),
		"/api/business/collections/{instance}": pathPost("Business", "Get collections", "Fetch WhatsApp Business collections", nil),
	}
}

// ── helpers ──

func strProp(desc, example string) map[string]any {
	return map[string]any{"type": "string", "description": desc, "example": example}
}
func numProp(desc string, example float64) map[string]any {
	return map[string]any{"type": "number", "description": desc, "example": example}
}
func boolProp(desc string, example bool) map[string]any {
	return map[string]any{"type": "boolean", "description": desc, "example": example}
}
func arrProp(desc string, example []string) map[string]any {
	return map[string]any{"type": "array", "description": desc, "items": map[string]string{"type": "string"}, "example": example}
}

func bodyObj(props map[string]any) map[string]any {
	return map[string]any{
		"required": true,
		"content": map[string]any{
			"application/json": map[string]any{
				"schema": map[string]any{"type": "object", "properties": props},
			},
		},
	}
}

func op(tag, summary, desc string) map[string]any {
	return map[string]any{
		"tags": []string{tag}, "summary": summary, "description": desc,
		"responses": map[string]any{"200": map[string]string{"description": "Success"}},
	}
}

func opBody(tag, summary, desc string, body map[string]any) map[string]any {
	o := op(tag, summary, desc)
	o["requestBody"] = body
	return o
}

func pathGet(tag, summary, desc string) map[string]any {
	return map[string]any{"get": op(tag, summary, desc)}
}

func pathPost(tag, summary, desc string, body map[string]any) map[string]any {
	if body != nil {
		return map[string]any{"post": opBody(tag, summary, desc, body)}
	}
	return map[string]any{"post": op(tag, summary, desc)}
}

func instanceParam() map[string]any {
	return map[string]any{
		"name": "instance", "in": "path", "required": true,
		"schema": map[string]string{"type": "string"}, "description": "Instance name",
	}
}

func formatParam() map[string]any {
	return map[string]any{
		"name": "format", "in": "query", "required": false,
		"schema":      map[string]any{"type": "string", "enum": []string{"png"}},
		"description": "Set to 'png' to get the QR code as a binary PNG image instead of JSON",
	}
}

func pathGetParam(tag, summary, desc, _ string) map[string]any {
	o := op(tag, summary, desc)
	o["parameters"] = []map[string]any{instanceParam()}
	return map[string]any{"get": o}
}

// pathGetQR documents GET endpoints backed by writeQRResponse: they return the
// QR code as a JSON data URL by default, or a binary PNG with ?format=png.
func pathGetQR(tag, summary, desc string) map[string]any {
	o := op(tag, summary, desc)
	o["parameters"] = []map[string]any{instanceParam(), formatParam()}
	o["responses"] = map[string]any{
		"200": map[string]any{
			"description": "QR code as JSON (data URL), or a binary PNG with ?format=png",
			"content": map[string]any{
				"application/json": map[string]any{
					"schema": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"instanceName": strProp("Instance name", "default"),
							"status":       strProp("Connection status", "qr"),
							"qr":           strProp("QR code as a data URL", "data:image/png;base64,..."),
						},
					},
				},
				"image/png": map[string]any{
					"schema": map[string]any{"type": "string", "format": "binary"},
				},
			},
		},
	}
	return map[string]any{"get": o}
}

func pathPostParam(tag, summary, desc, _ string) map[string]any {
	o := op(tag, summary, desc)
	o["parameters"] = []map[string]any{instanceParam()}
	return map[string]any{"post": o}
}

func pathDelParam(tag, summary, desc, _ string) map[string]any {
	o := op(tag, summary, desc)
	o["parameters"] = []map[string]any{instanceParam()}
	return map[string]any{"delete": o}
}
