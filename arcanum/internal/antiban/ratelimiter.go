// Package antiban implementa medidas de protecao contra banimento do WhatsApp.
// Inclui rate limiting por sliding window e delays humanizados com indicadores de presenca.
package antiban

import (
	"sync"
	"time"
)

// RateLimiter controla a taxa de envio de mensagens usando sliding window.
// Thread-safe via sync.Mutex — seguro para uso concorrente em handlers HTTP.
type RateLimiter struct {
	mu         sync.Mutex
	timestamps []int64
	limit      int
	windowMs   int64
}

// NewRateLimiter cria um rate limiter com o limite de mensagens por minuto.
func NewRateLimiter(limit int) *RateLimiter {
	return &RateLimiter{
		limit:    limit,
		windowMs: 60_000,
	}
}

// Allow verifica se uma nova mensagem pode ser enviada.
// Retorna true e registra o timestamp se dentro do limite.
// Retorna false se o limite foi excedido na janela de 60 segundos.
func (r *RateLimiter) Allow() bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now().UnixMilli()
	r.prune(now)

	if len(r.timestamps) >= r.limit {
		return false
	}

	r.timestamps = append(r.timestamps, now)
	return true
}

// Usage retorna o uso atual (mensagens na janela) e o limite configurado.
func (r *RateLimiter) Usage() (current int, limit int) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.prune(time.Now().UnixMilli())
	return len(r.timestamps), r.limit
}

// prune remove timestamps fora da janela de 60 segundos.
func (r *RateLimiter) prune(now int64) {
	cutoff := now - r.windowMs
	i := 0
	for i < len(r.timestamps) && r.timestamps[i] < cutoff {
		i++
	}
	r.timestamps = r.timestamps[i:]
}
