# Changelog

Todas as mudanças notaveis do projeto serao documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o projeto adere ao [Versionamento Semantico](https://semver.org/lang/pt-BR/).

## [1.0.0] - 2026-06-20

### Adicionado

- **Multi-instancia** — crie e gerencie multiplas conexoes WhatsApp simultaneamente
- **Autenticacao** via QR Code e Phone Pairing (codigo de 8 digitos)
- **Envio de mensagens** com anti-ban integrado:
  - Texto (com delay aleatorio + indicador "digitando...")
  - Imagens (JPEG, PNG) com caption
  - Documentos (PDF, DOCX) com filename
  - Audio/voz (OGG, MP3) com indicador "gravando..."
  - Video (MP4) com caption
  - Localizacao (GPS com nome e endereco)
  - Contato (vCard)
  - Reacao (emoji em mensagem existente)
  - Enquete (poll com opcoes)
- **Recebimento de mensagens** com download automatico de midia
- **Webhook forwarding** com assinatura HMAC-SHA256
- **Anti-ban nativo**:
  - Delay aleatorio antes de responder (1.5-4s configuravel)
  - Indicador "digitando..." proporcional ao tamanho do texto
  - Indicador "gravando..." para audios
  - Read receipts antes de responder
  - Rate limiting (15 msg/min por instancia)
- **Configuracoes por instancia** (rejectCalls, groupsIgnore, alwaysOnline, readMessages)
- **Webhook configuravel via API** (URL, eventos, habilitar/desabilitar)
- **Swagger UI** com documentacao interativa em `/docs`
- **Docker** com multi-stage build (Go 1.25 + Alpine)
- **Verificacao de numeros** (checkWhatsAppNumbers)
- **Gerenciamento de perfil** (nome, status, foto)
- **Chat operations** (marcar como lido, arquivar)

### Arquitetura

- Go 1.25 + whatsmeow (engine de protocolo WhatsApp)
- Chi v5 (HTTP router)
- SQLite (sessoes persistentes por instancia)
- Interface `WhatsAppProvider` — provider-agnostico, permite trocar engine
- Zero dependencia de projetos externos
