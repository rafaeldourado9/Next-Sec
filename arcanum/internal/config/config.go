// Package config carrega a configuracao do Arcanum API a partir de variaveis de ambiente.
// Todas as variaveis usam o prefixo GATEWAY_ e possuem valores padrao seguros para desenvolvimento.
package config

import (
	"os"
	"strconv"
)

// Config armazena todas as configuracoes do gateway.
// Cada campo mapeia para uma variavel de ambiente com prefixo GATEWAY_.
type Config struct {
	// Port define a porta HTTP do servidor (GATEWAY_PORT, padrao: 3100).
	Port int

	// WebhookForwardURL e a URL padrao para encaminhar mensagens recebidas via webhook.
	// Pode ser sobrescrita por instancia via API (GATEWAY_WEBHOOK_FORWARD_URL).
	WebhookForwardURL string

	// WebhookFormat define o formato do webhook: "meta" (compativel com Meta Cloud API)
	// ou "simple" (formato simplificado para integracao direta com agent-core).
	// Padrao: "meta" para compatibilidade. Use "simple" para integracoes novas.
	// (GATEWAY_WEBHOOK_FORMAT)
	WebhookFormat string

	// WebhookSecret e o secret usado para assinar webhooks com HMAC-SHA256.
	// Se vazio, os webhooks sao enviados sem assinatura (GATEWAY_META_APP_SECRET).
	WebhookSecret string

	// DBPath e o diretorio onde os arquivos SQLite de sessao sao armazenados.
	// Cada instancia cria um arquivo .db separado (GATEWAY_DB_PATH, padrao: ./data).
	DBPath string

	// MinDelayMs e o delay minimo (ms) antes de enviar uma mensagem — parte do anti-ban.
	MinDelayMs int

	// MaxDelayMs e o delay maximo (ms) antes de enviar uma mensagem — parte do anti-ban.
	MaxDelayMs int

	// TypingDurationMs e a duracao minima (ms) do indicador "digitando..." antes de enviar.
	TypingDurationMs int

	// MsPerChar define quantos milissegundos o "digitando..." dura por caractere da mensagem.
	MsPerChar int

	// MaxTypingMs e a duracao maxima (ms) do indicador "digitando..." independente do tamanho.
	MaxTypingMs int

	// RateLimitPerMin define o numero maximo de mensagens enviadas por minuto por instancia.
	RateLimitPerMin int
}

// Load carrega a configuracao a partir das variaveis de ambiente.
// Valores ausentes usam os padroes definidos.
func Load() *Config {
	return &Config{
		Port:              envInt("GATEWAY_PORT", 3100),
		WebhookForwardURL: envStr("GATEWAY_WEBHOOK_FORWARD_URL", ""),
		WebhookFormat:     envStr("GATEWAY_WEBHOOK_FORMAT", "simple"),
		WebhookSecret:     envStr("GATEWAY_META_APP_SECRET", ""),
		DBPath:            envStr("GATEWAY_DB_PATH", "./data"),

		MinDelayMs:       envInt("GATEWAY_MIN_DELAY_MS", 1500),
		MaxDelayMs:       envInt("GATEWAY_MAX_DELAY_MS", 4000),
		TypingDurationMs: envInt("GATEWAY_TYPING_DURATION_MS", 2000),
		MsPerChar:        envInt("GATEWAY_MS_PER_CHAR", 50),
		MaxTypingMs:      envInt("GATEWAY_MAX_TYPING_MS", 8000),
		RateLimitPerMin:  envInt("GATEWAY_RATE_LIMIT_PER_MIN", 15),
	}
}

func envStr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}
