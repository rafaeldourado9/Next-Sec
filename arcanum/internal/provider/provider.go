// Package provider define a interface abstrata para engines de WhatsApp.
// Qualquer implementacao (whatsmeow, Meta Cloud API, etc.) deve satisfazer
// a interface WhatsAppProvider, permitindo trocar o engine sem alterar a API REST.
package provider

// ConnectionStatus representa o estado atual da conexao com o WhatsApp.
type ConnectionStatus string

const (
	// StatusDisconnected indica que nao ha conexao ativa.
	StatusDisconnected ConnectionStatus = "disconnected"
	// StatusConnecting indica que uma conexao esta sendo estabelecida.
	StatusConnecting ConnectionStatus = "connecting"
	// StatusQR indica que um QR code foi gerado e aguarda leitura pelo celular.
	StatusQR ConnectionStatus = "qr"
	// StatusConnected indica que a conexao esta ativa e pronta para enviar/receber.
	StatusConnected ConnectionStatus = "connected"
)

// SendTextOptions contem os parametros para envio de mensagem de texto.
type SendTextOptions struct {
	To   string `json:"to"`   // Numero do destinatario com codigo do pais (ex: 5511999999999)
	Text string `json:"text"` // Conteudo da mensagem
}

// SendMediaOptions contem os parametros para envio de midia (imagem, audio, documento, video).
type SendMediaOptions struct {
	To       string `json:"to"`                // Numero do destinatario
	Type     string `json:"type"`              // Tipo: "image", "audio", "document", "video"
	Data     []byte `json:"-"`                 // Bytes do arquivo (alternativa a URL)
	URL      string `json:"url,omitempty"`     // URL do arquivo (alternativa a Data)
	MimeType string `json:"mimetype"`          // MIME type (ex: image/jpeg, application/pdf)
	Filename string `json:"filename,omitempty"` // Nome do arquivo (para documentos)
	Caption  string `json:"caption,omitempty"` // Legenda (para imagens e videos)
}

// SendResult e o retorno de qualquer operacao de envio bem-sucedida.
type SendResult struct {
	MessageID string `json:"messageId"` // ID da mensagem gerado pelo WhatsApp
	Provider  string `json:"provider"`  // Nome do provider que enviou (ex: "whatsmeow")
	Timestamp int64  `json:"timestamp"` // Timestamp Unix em milissegundos
}

// MediaData representa midia recebida (download ja feito, descriptografado).
type MediaData struct {
	MimeType string `json:"mimetype"`          // MIME type do arquivo
	Data     []byte `json:"-"`                 // Bytes brutos (nao serializado no JSON)
	DataB64  string `json:"data,omitempty"`    // Dados em base64 (usado no webhook)
	Filename string `json:"filename,omitempty"` // Nome original do arquivo
	Caption  string `json:"caption,omitempty"` // Legenda (se houver)
}

// IncomingMessage representa uma mensagem recebida de qualquer tipo.
// O campo Type indica o tipo: "text", "image", "audio", "document", "video", "sticker", "unknown".
// Para mensagens com midia, o campo Media contem os bytes ja baixados.
type IncomingMessage struct {
	MessageID string     `json:"messageId"`          // ID unico da mensagem
	From      string     `json:"from"`               // Numero do remetente
	Timestamp int64      `json:"timestamp"`           // Timestamp Unix
	PushName  string     `json:"pushName,omitempty"` // Nome de exibicao do remetente
	Type      string     `json:"type"`               // Tipo da mensagem
	Text      string     `json:"text,omitempty"`     // Texto (para type=text) ou caption (para midia)
	Media     *MediaData `json:"media,omitempty"`    // Midia anexada (nil se for apenas texto)
}

// MessageHandler e o callback chamado quando uma nova mensagem e recebida.
type MessageHandler func(msg IncomingMessage)

// WhatsAppProvider e a interface principal que qualquer engine de WhatsApp deve implementar.
// O Arcanum usa essa interface para desacoplar a API REST do protocolo subjacente.
//
// Implementacoes atuais:
//   - WhatsmeowProvider: usa whatsmeow (protocolo WhatsApp Web nativo)
//
// Todos os metodos de envio devem ser chamados apenas quando Status() == StatusConnected.
type WhatsAppProvider interface {
	// Name retorna o identificador do provider (ex: "whatsmeow").
	Name() string
	// Connect inicia a conexao com o WhatsApp. Pode gerar QR code.
	Connect() error
	// Disconnect encerra a conexao.
	Disconnect() error
	// Status retorna o estado atual da conexao.
	Status() ConnectionStatus
	// QRCode retorna o QR code atual como string (vazio se nao houver).
	QRCode() string

	// SendText envia uma mensagem de texto.
	SendText(opts SendTextOptions) (SendResult, error)
	// SendMedia envia uma midia (imagem, audio, documento ou video).
	SendMedia(opts SendMediaOptions) (SendResult, error)
	// SendPresence envia indicador de presenca ("composing", "recording", "paused", "available").
	SendPresence(to string, presenceType string) error
	// MarkAsRead envia confirmacao de leitura para uma mensagem.
	MarkAsRead(messageID string, from string) error

	// OnMessage registra o callback para mensagens recebidas.
	OnMessage(handler MessageHandler)

	// SendLocation envia uma localizacao GPS.
	SendLocation(opts SendLocationOptions) (SendResult, error)
	// SendContact envia um ou mais cartoes de contato (vCard).
	SendContact(opts SendContactOptions) (SendResult, error)
	// SendReaction envia uma reacao (emoji) a uma mensagem existente.
	SendReaction(opts SendReactionOptions) (SendResult, error)
	// SendPoll envia uma enquete com opcoes.
	SendPoll(opts SendPollOptions) (SendResult, error)

	// CheckNumbers verifica quais numeros possuem WhatsApp.
	CheckNumbers(numbers []string) ([]NumberCheck, error)
	// UpdateProfileName atualiza o nome de exibicao do perfil.
	UpdateProfileName(name string) error
	// UpdateProfileStatus atualiza o texto de status/about do perfil.
	UpdateProfileStatus(status string) error
	// UpdateProfilePicture atualiza a foto do perfil (base64 da imagem).
	UpdateProfilePicture(base64Image string) error

	// PairPhone inicia o pairing via numero de telefone (alternativa ao QR).
	// Retorna o codigo de 8 digitos que o usuario deve inserir no WhatsApp.
	PairPhone(phone string) (string, error)
}

// NumberCheck e o resultado da verificacao de um numero no WhatsApp.
type NumberCheck struct {
	Number string `json:"number"` // Numero consultado
	Exists bool   `json:"exists"` // true se o numero possui WhatsApp
	JID    string `json:"jid,omitempty"` // JID do WhatsApp (se existir)
}

// SendLocationOptions contem os parametros para envio de localizacao.
type SendLocationOptions struct {
	To        string  `json:"to"`                 // Numero do destinatario
	Latitude  float64 `json:"latitude"`           // Latitude GPS
	Longitude float64 `json:"longitude"`          // Longitude GPS
	Name      string  `json:"name,omitempty"`     // Nome do local
	Address   string  `json:"address,omitempty"` // Endereco textual
}

// SendReactionOptions contem os parametros para envio de reacao.
type SendReactionOptions struct {
	To        string `json:"to"`        // JID do chat
	MessageID string `json:"messageId"` // ID da mensagem a reagir
	Emoji     string `json:"emoji"`     // Emoji da reacao (ex: "👍")
}

// ContactCard representa um contato para envio via vCard.
type ContactCard struct {
	FullName    string `json:"fullName"`    // Nome completo do contato
	PhoneNumber string `json:"phoneNumber"` // Numero de telefone
}

// SendContactOptions contem os parametros para envio de contato(s).
type SendContactOptions struct {
	To       string        `json:"to"`       // Numero do destinatario
	Contacts []ContactCard `json:"contacts"` // Lista de contatos
}

// SendPollOptions contem os parametros para envio de enquete.
type SendPollOptions struct {
	To              string   `json:"to"`              // Numero do destinatario
	Name            string   `json:"name"`            // Pergunta da enquete
	Options         []string `json:"options"`         // Opcoes de resposta
	SelectableCount int      `json:"selectableCount"` // Maximo de opcoes selecionaveis
}
