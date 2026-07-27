package provider

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/rafaeldourado9/arcanum/internal/media"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waCompanionReg"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

// WhatsApp's Linked Devices screen picks an icon from a fixed set tied to
// PlatformType (browser logos, phone, desktop, ...) — there's no way to show
// a custom logo image. DESKTOP gives a generic computer icon next to our name
// instead of the "Outro dispositivo"/question-mark fallback for UNKNOWN.
func init() {
	store.DeviceProps.Os = proto.String("Arcanum")
	store.DeviceProps.PlatformType = waCompanionReg.DeviceProps_DESKTOP.Enum()
}

type WhatsmeowProvider struct {
	dbPath            string
	client            *whatsmeow.Client
	container         *sqlstore.Container
	status            ConnectionStatus
	qrCode            string
	handler           MessageHandler
	mu                sync.RWMutex
	reconnectAttempts int
	maxReconnects     int
}

func NewWhatsmeow(dbPath string) *WhatsmeowProvider {
	return &WhatsmeowProvider{
		dbPath:        dbPath,
		status:        StatusDisconnected,
		maxReconnects: 10,
	}
}

func (w *WhatsmeowProvider) Name() string { return "whatsmeow" }

func (w *WhatsmeowProvider) Status() ConnectionStatus {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.status
}

func (w *WhatsmeowProvider) QRCode() string {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.qrCode
}

func (w *WhatsmeowProvider) setStatus(s ConnectionStatus) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.status = s
}

func (w *WhatsmeowProvider) setQR(qr string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.qrCode = qr
}

func (w *WhatsmeowProvider) Connect() error {
	// Reconecta reaproveitando o client/container já existentes — reconstruí-los
	// a cada reconnect() abria uma segunda conexão ao MESMO arquivo sqlite e um
	// segundo *whatsmeow.Client concorrendo pela mesma sessão, o que fazia o
	// WhatsApp derrubar a conexão quase na hora (novo QR, timeout, reconnect,
	// outro client novo — loop infinito observado em teste local: "Connected"
	// seguido quase imediatamente de "QR code ready" de novo).
	if w.client == nil {
		logger := waLog.Noop

		container, err := sqlstore.New(context.Background(), "sqlite3", "file:"+w.dbPath+"?_foreign_keys=on", logger)
		if err != nil {
			return fmt.Errorf("sqlstore: %w", err)
		}
		w.container = container

		deviceStore, err := container.GetFirstDevice(context.Background())
		if err != nil {
			return fmt.Errorf("device store: %w", err)
		}

		w.client = whatsmeow.NewClient(deviceStore, logger)
		w.client.AddEventHandler(w.eventHandler)
	}

	if w.client.Store.ID == nil {
		return w.connectWithQR()
	}

	w.setStatus(StatusConnecting)
	return w.client.Connect()
}

func (w *WhatsmeowProvider) connectWithQR() error {
	qrChan, _ := w.client.GetQRChannel(context.Background())

	err := w.client.Connect()
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}

	go func() {
		for evt := range qrChan {
			switch evt.Event {
			case "code":
				w.setQR(evt.Code)
				w.setStatus(StatusQR)
				log.Println("[whatsmeow] QR code ready — scan with WhatsApp")
				log.Println("[whatsmeow] Or open http://localhost:3100/api/qr?format=png")
			case "success":
				w.setQR("")
				log.Println("[whatsmeow] Pairing successful")
			case "timeout":
				log.Println("[whatsmeow] QR timeout — reconnecting")
				w.setQR("")
				w.reconnect()
			}
		}
	}()

	return nil
}

func (w *WhatsmeowProvider) eventHandler(evt interface{}) {
	switch v := evt.(type) {
	case *events.Connected:
		w.setStatus(StatusConnected)
		w.setQR("")
		w.reconnectAttempts = 0
		log.Println("[whatsmeow] Connected")

	case *events.Disconnected:
		log.Println("[whatsmeow] Disconnected")
		w.reconnect()

	case *events.LoggedOut:
		w.setStatus(StatusDisconnected)
		w.setQR("")
		log.Println("[whatsmeow] Logged out — delete data/ and restart to re-pair")

	case *events.Message:
		w.handleMessage(v)

	case *events.HistorySync:
		// ignore
	}
}

func (w *WhatsmeowProvider) handleMessage(evt *events.Message) {
	w.mu.RLock()
	handler := w.handler
	w.mu.RUnlock()

	if handler == nil {
		return
	}

	if evt.Info.IsFromMe {
		return
	}
	if evt.Info.Chat.Server == "g.us" {
		return
	}

	msg := IncomingMessage{
		MessageID: evt.Info.ID,
		// Sender.String() keeps the JID server (e.g. "@lid" vs "@s.whatsapp.net").
		// WhatsApp increasingly routes senders through LIDs, which live in a
		// different numeric namespace than phone numbers — replying with just
		// the bare user-part number (as if it were always a phone number) sends
		// to a nonexistent account and the message silently never arrives.
		From:      evt.Info.Sender.String(),
		Timestamp: evt.Info.Timestamp.Unix(),
		PushName:  evt.Info.PushName,
		Type:      "unknown",
	}

	raw := evt.Message

	if raw.GetConversation() != "" {
		msg.Type = "text"
		msg.Text = raw.GetConversation()
	} else if raw.GetExtendedTextMessage() != nil {
		msg.Type = "text"
		msg.Text = raw.GetExtendedTextMessage().GetText()
	} else if im := raw.GetImageMessage(); im != nil {
		msg.Type = "image"
		msg.Text = im.GetCaption()
		msg.Media = w.downloadSubMedia(im, im.GetMimetype())
	} else if am := raw.GetAudioMessage(); am != nil {
		msg.Type = "audio"
		msg.Media = w.downloadSubMedia(am, am.GetMimetype())
	} else if dm := raw.GetDocumentMessage(); dm != nil {
		msg.Type = "document"
		msg.Text = dm.GetCaption()
		md := w.downloadSubMedia(dm, dm.GetMimetype())
		if md != nil {
			md.Filename = dm.GetFileName()
		}
		msg.Media = md
	} else if vm := raw.GetVideoMessage(); vm != nil {
		msg.Type = "video"
		msg.Text = vm.GetCaption()
		msg.Media = w.downloadSubMedia(vm, vm.GetMimetype())
	} else if raw.GetStickerMessage() != nil {
		msg.Type = "sticker"
	}

	handler(msg)
}

func (w *WhatsmeowProvider) downloadSubMedia(msg whatsmeow.DownloadableMessage, mimetype string) *MediaData {
	data, err := w.client.Download(context.Background(), msg)
	if err != nil {
		log.Printf("[whatsmeow] media download failed: %v", err)
		return nil
	}
	return &MediaData{
		MimeType: mimetype,
		Data:     data,
	}
}

func (w *WhatsmeowProvider) reconnect() {
	w.reconnectAttempts++
	if w.reconnectAttempts > w.maxReconnects {
		w.setStatus(StatusDisconnected)
		log.Println("[whatsmeow] Max reconnect attempts reached")
		return
	}

	delay := time.Duration(5*w.reconnectAttempts) * time.Second
	if delay > 30*time.Second {
		delay = 30 * time.Second
	}
	w.setStatus(StatusConnecting)
	log.Printf("[whatsmeow] Reconnecting in %v (attempt %d/%d)", delay, w.reconnectAttempts, w.maxReconnects)

	time.AfterFunc(delay, func() {
		if w.client != nil {
			w.client.Disconnect()
		}
		if err := w.Connect(); err != nil {
			log.Printf("[whatsmeow] Reconnect failed: %v", err)
		}
	})
}

func (w *WhatsmeowProvider) Disconnect() error {
	if w.client != nil {
		w.client.Disconnect()
	}
	return nil
}

// plainDigitsJID builds a JID by taking the input at face value: strips
// everything but digits and assumes it's a phone number on the default user
// server. Used as a last-resort fallback when a proper lookup isn't possible.
func plainDigitsJID(to string) types.JID {
	clean := strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, to)
	return types.NewJID(clean, types.DefaultUserServer)
}

// resolveJID builds the JID to send to. If the input is already a full JID
// (e.g. "104200855892049@lid", as received from incoming messages — see
// OnMessage), it's parsed as-is so replies go back through the same
// identifier namespace the message came from.
//
// Plain digit strings are resolved via IsOnWhatsApp first. Isto NÃO é sobre
// LID — é normalização de dígito: os dois contatos cadastrados neste tenant
// (confirmado via checkWhatsAppNumbers) estão salvos com 13 dígitos (9
// extra do celular), mas o WhatsApp tem as duas contas registradas com 12
// (formato antigo). Sem essa resolução, o servidor rejeita com "no LID
// found" pros DOIS números, não só um — chegou a ser removido e revertido
// no mesmo teste local depois de confirmar a regressão. IsOnWhatsApp
// devolve o JID canônico que o WhatsApp realmente tem cadastrado.
func (w *WhatsmeowProvider) resolveJID(to string) types.JID {
	if strings.Contains(to, "@") {
		if jid, err := types.ParseJID(to); err == nil {
			return jid
		}
	}

	fallback := plainDigitsJID(to)
	if w.client == nil {
		return fallback
	}

	resp, err := w.client.IsOnWhatsApp(context.Background(), []string{"+" + fallback.User})
	if err != nil || len(resp) == 0 || !resp[0].IsIn {
		return fallback
	}
	return resp[0].JID
}

func (w *WhatsmeowProvider) SendText(opts SendTextOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), &waE2E.Message{
		Conversation: proto.String(opts.Text),
	})
	if err != nil {
		return SendResult{}, err
	}

	return SendResult{
		MessageID: resp.ID,
		Provider:  "whatsmeow",
		Timestamp: time.Now().UnixMilli(),
	}, nil
}

func (w *WhatsmeowProvider) SendMedia(opts SendMediaOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	data := opts.Data
	if len(data) == 0 && opts.URL != "" {
		return SendResult{}, fmt.Errorf("URL-based media send not supported, provide data bytes")
	}

	var mediaType whatsmeow.MediaType
	switch opts.Type {
	case "image":
		mediaType = whatsmeow.MediaImage
	case "audio":
		mediaType = whatsmeow.MediaAudio
	case "document":
		mediaType = whatsmeow.MediaDocument
	case "video":
		mediaType = whatsmeow.MediaVideo
	default:
		mediaType = whatsmeow.MediaDocument
	}

	uploaded, err := w.client.Upload(context.Background(), data, mediaType)
	if err != nil {
		return SendResult{}, fmt.Errorf("upload: %w", err)
	}

	var msg *waE2E.Message
	switch opts.Type {
	case "image":
		msg = &waE2E.Message{
			ImageMessage: &waE2E.ImageMessage{
				Caption:       proto.String(opts.Caption),
				URL:           proto.String(uploaded.URL),
				DirectPath:    proto.String(uploaded.DirectPath),
				MediaKey:      uploaded.MediaKey,
				FileEncSHA256: uploaded.FileEncSHA256,
				FileSHA256:    uploaded.FileSHA256,
				FileLength:    proto.Uint64(uploaded.FileLength),
				Mimetype:      proto.String(opts.MimeType),
			},
		}
	case "audio":
		ptt := strings.Contains(opts.MimeType, "ogg")
		msg = &waE2E.Message{
			AudioMessage: &waE2E.AudioMessage{
				URL:           proto.String(uploaded.URL),
				DirectPath:    proto.String(uploaded.DirectPath),
				MediaKey:      uploaded.MediaKey,
				FileEncSHA256: uploaded.FileEncSHA256,
				FileSHA256:    uploaded.FileSHA256,
				FileLength:    proto.Uint64(uploaded.FileLength),
				Mimetype:      proto.String(opts.MimeType),
				PTT:           proto.Bool(ptt),
			},
		}
	case "video":
		msg = &waE2E.Message{
			VideoMessage: &waE2E.VideoMessage{
				Caption:       proto.String(opts.Caption),
				URL:           proto.String(uploaded.URL),
				DirectPath:    proto.String(uploaded.DirectPath),
				MediaKey:      uploaded.MediaKey,
				FileEncSHA256: uploaded.FileEncSHA256,
				FileSHA256:    uploaded.FileSHA256,
				FileLength:    proto.Uint64(uploaded.FileLength),
				Mimetype:      proto.String(opts.MimeType),
			},
		}
	default:
		msg = &waE2E.Message{
			DocumentMessage: &waE2E.DocumentMessage{
				Caption:       proto.String(opts.Caption),
				FileName:      proto.String(opts.Filename),
				URL:           proto.String(uploaded.URL),
				DirectPath:    proto.String(uploaded.DirectPath),
				MediaKey:      uploaded.MediaKey,
				FileEncSHA256: uploaded.FileEncSHA256,
				FileSHA256:    uploaded.FileSHA256,
				FileLength:    proto.Uint64(uploaded.FileLength),
				Mimetype:      proto.String(opts.MimeType),
			},
		}
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), msg)
	if err != nil {
		return SendResult{}, err
	}

	return SendResult{
		MessageID: resp.ID,
		Provider:  "whatsmeow",
		Timestamp: time.Now().UnixMilli(),
	}, nil
}

func (w *WhatsmeowProvider) SendPresence(to string, presenceType string) error {
	if w.client == nil || w.Status() != StatusConnected {
		return nil
	}

	jid := w.resolveJID(to)
	ctx := context.Background()
	switch presenceType {
	case "composing":
		return w.client.SendChatPresence(ctx, jid, types.ChatPresenceComposing, types.ChatPresenceMediaText)
	case "recording":
		return w.client.SendChatPresence(ctx, jid, types.ChatPresenceComposing, types.ChatPresenceMediaAudio)
	case "paused":
		return w.client.SendChatPresence(ctx, jid, types.ChatPresencePaused, "")
	case "available":
		return w.client.SendPresence(ctx, types.PresenceAvailable)
	}
	return nil
}

func (w *WhatsmeowProvider) MarkAsRead(messageID string, from string) error {
	if w.client == nil || w.Status() != StatusConnected || messageID == "" {
		return nil
	}
	return w.client.MarkRead(context.Background(), []types.MessageID{messageID}, time.Now(), w.resolveJID(from), types.EmptyJID)
}

func (w *WhatsmeowProvider) OnMessage(handler MessageHandler) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.handler = handler
}

func (w *WhatsmeowProvider) SendLocation(opts SendLocationOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), &waE2E.Message{
		LocationMessage: &waE2E.LocationMessage{
			DegreesLatitude:  proto.Float64(opts.Latitude),
			DegreesLongitude: proto.Float64(opts.Longitude),
			Name:             proto.String(opts.Name),
			Address:          proto.String(opts.Address),
		},
	})
	if err != nil {
		return SendResult{}, err
	}
	return SendResult{MessageID: resp.ID, Provider: "whatsmeow", Timestamp: time.Now().UnixMilli()}, nil
}

func (w *WhatsmeowProvider) SendContact(opts SendContactOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	var vcards []string
	for _, c := range opts.Contacts {
		vcard := fmt.Sprintf("BEGIN:VCARD\nVERSION:3.0\nFN:%s\nTEL;type=CELL:+%s\nEND:VCARD", c.FullName, c.PhoneNumber)
		vcards = append(vcards, vcard)
	}

	var msg *waE2E.Message
	if len(vcards) == 1 {
		msg = &waE2E.Message{
			ContactMessage: &waE2E.ContactMessage{
				DisplayName: proto.String(opts.Contacts[0].FullName),
				Vcard:       proto.String(vcards[0]),
			},
		}
	} else {
		combined := ""
		for _, v := range vcards {
			combined += v + "\n"
		}
		msg = &waE2E.Message{
			ContactMessage: &waE2E.ContactMessage{
				DisplayName: proto.String("Contacts"),
				Vcard:       proto.String(combined),
			},
		}
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), msg)
	if err != nil {
		return SendResult{}, err
	}
	return SendResult{MessageID: resp.ID, Provider: "whatsmeow", Timestamp: time.Now().UnixMilli()}, nil
}

func (w *WhatsmeowProvider) SendReaction(opts SendReactionOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), w.client.BuildReaction(w.resolveJID(opts.To), types.EmptyJID, opts.MessageID, opts.Emoji))
	if err != nil {
		return SendResult{}, err
	}
	return SendResult{MessageID: resp.ID, Provider: "whatsmeow", Timestamp: time.Now().UnixMilli()}, nil
}

func (w *WhatsmeowProvider) SendPoll(opts SendPollOptions) (SendResult, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return SendResult{}, fmt.Errorf("not connected")
	}

	resp, err := w.client.SendMessage(context.Background(), w.resolveJID(opts.To), w.client.BuildPollCreation(opts.Name, opts.Options, opts.SelectableCount))
	if err != nil {
		return SendResult{}, err
	}
	return SendResult{MessageID: resp.ID, Provider: "whatsmeow", Timestamp: time.Now().UnixMilli()}, nil
}

func (w *WhatsmeowProvider) CheckNumbers(numbers []string) ([]NumberCheck, error) {
	if w.client == nil || w.Status() != StatusConnected {
		return nil, fmt.Errorf("not connected")
	}

	results := make([]NumberCheck, 0, len(numbers))
	for _, num := range numbers {
		jid := plainDigitsJID(num)
		resp, err := w.client.IsOnWhatsApp(context.Background(), []string{"+" + jid.User})
		if err != nil {
			results = append(results, NumberCheck{Number: num, Exists: false})
			continue
		}
		for _, r := range resp {
			results = append(results, NumberCheck{
				Number: num,
				Exists: r.IsIn,
				JID:    r.JID.String(),
			})
		}
	}
	return results, nil
}

func (w *WhatsmeowProvider) UpdateProfileName(name string) error {
	if w.client == nil || w.Status() != StatusConnected {
		return fmt.Errorf("not connected")
	}
	return w.client.SetStatusMessage(context.Background(),name)
}

func (w *WhatsmeowProvider) UpdateProfileStatus(status string) error {
	if w.client == nil || w.Status() != StatusConnected {
		return fmt.Errorf("not connected")
	}
	return w.client.SetStatusMessage(context.Background(),status)
}

func (w *WhatsmeowProvider) UpdateProfilePicture(base64Image string) error {
	if w.client == nil || w.Status() != StatusConnected {
		return fmt.Errorf("not connected")
	}
	data, err := media.FromBase64(base64Image)
	if err != nil {
		return fmt.Errorf("invalid base64: %w", err)
	}
	_, err = w.client.SetGroupPhoto(context.Background(), w.client.Store.ID.ToNonAD(), data)
	return err
}


func (w *WhatsmeowProvider) PairPhone(phone string) (string, error) {
	if w.client == nil {
		return "", fmt.Errorf("not initialized")
	}
	code, err := w.client.PairPhone(context.Background(), phone, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
	if err != nil {
		return "", err
	}
	return code, nil
}
