package api

import (
	"encoding/json"
	"log"
	"net/http"
	"time"
)

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

// sendWithRetry runs a send operation with a few short retries. Sends happen
// in a background goroutine (see handleSendText) with no caller waiting on
// the result, so a transient failure (e.g. a WhatsApp usync query timeout)
// would otherwise silently drop the message — this gives it a few chances to
// go through before giving up and just logging it.
func sendWithRetry(to string, send func() error) {
	const maxAttempts = 3
	backoff := 500 * time.Millisecond

	var err error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		if err = send(); err == nil {
			return
		}
		log.Printf("[send] attempt %d/%d to %s failed: %v", attempt, maxAttempts, to, err)
		if attempt < maxAttempts {
			time.Sleep(backoff)
			backoff *= 2
		}
	}
	log.Printf("[send] giving up on %s after %d attempts: %v", to, maxAttempts, err)
}
