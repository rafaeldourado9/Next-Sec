package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rafaeldourado9/arcanum/internal/config"
	"github.com/rafaeldourado9/arcanum/internal/instance"
	"github.com/rafaeldourado9/arcanum/internal/provider"
)

// fakeProvider is a minimal provider.WhatsAppProvider for tests — it never
// touches the network. SendText records how long the caller waited for it,
// and can be configured to fail the first N calls (to test retry behavior).
type fakeProvider struct {
	mu           sync.Mutex
	sendTextCall chan struct{}
	failTimes    int
	attempts     int
}

func (f *fakeProvider) attemptCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.attempts
}

func (f *fakeProvider) Name() string                      { return "fake" }
func (f *fakeProvider) Connect() error                    { return nil }
func (f *fakeProvider) Disconnect() error                 { return nil }
func (f *fakeProvider) Status() provider.ConnectionStatus { return provider.StatusConnected }
func (f *fakeProvider) QRCode() string                    { return "" }
func (f *fakeProvider) SendPresence(string, string) error { return nil }
func (f *fakeProvider) MarkAsRead(string, string) error   { return nil }
func (f *fakeProvider) OnMessage(provider.MessageHandler) {}
func (f *fakeProvider) CheckNumbers([]string) ([]provider.NumberCheck, error) {
	return nil, nil
}
func (f *fakeProvider) UpdateProfileName(string) error    { return nil }
func (f *fakeProvider) UpdateProfileStatus(string) error  { return nil }
func (f *fakeProvider) UpdateProfilePicture(string) error { return nil }
func (f *fakeProvider) PairPhone(string) (string, error)  { return "", nil }
func (f *fakeProvider) SendLocation(provider.SendLocationOptions) (provider.SendResult, error) {
	return provider.SendResult{}, nil
}
func (f *fakeProvider) SendContact(provider.SendContactOptions) (provider.SendResult, error) {
	return provider.SendResult{}, nil
}
func (f *fakeProvider) SendReaction(provider.SendReactionOptions) (provider.SendResult, error) {
	return provider.SendResult{}, nil
}
func (f *fakeProvider) SendPoll(provider.SendPollOptions) (provider.SendResult, error) {
	return provider.SendResult{}, nil
}
func (f *fakeProvider) SendMedia(provider.SendMediaOptions) (provider.SendResult, error) {
	return provider.SendResult{}, nil
}

func (f *fakeProvider) SendText(opts provider.SendTextOptions) (provider.SendResult, error) {
	f.mu.Lock()
	f.attempts++
	shouldFail := f.attempts <= f.failTimes
	f.mu.Unlock()

	if shouldFail {
		return provider.SendResult{}, errTransient
	}

	if f.sendTextCall != nil {
		close(f.sendTextCall)
	}
	return provider.SendResult{MessageID: "fake-id", Provider: "fake"}, nil
}

var errTransient = errors.New("transient send failure")

func newTestServer(t *testing.T, fp *fakeProvider) (http.Handler, *instance.Manager) {
	t.Helper()

	cfg := &config.Config{
		DBPath: t.TempDir(),
		// Anti-ban delay deliberately well above the response-time assertion's
		// threshold (500ms) — if the handler ever goes back to blocking on
		// this, the first assertion below will fail.
		MinDelayMs:       1500,
		MaxDelayMs:       1500,
		TypingDurationMs: 1500,
		MaxTypingMs:      1500,
		MsPerChar:        50,
		RateLimitPerMin:  100,
	}

	mgr := instance.NewManager(cfg)
	inst, err := mgr.Create("test", "", nil)
	if err != nil {
		t.Fatalf("create instance: %v", err)
	}
	inst.Provider = fp

	return NewServer(mgr, cfg), mgr
}

// TestSendTextRespondsBeforeAntiBanDelayCompletes is a regression test for a
// production bug: handleSendText used to call antiban.HumanizedSend
// synchronously before responding, blocking the HTTP response for the full
// anti-ban delay (up to ~13s with defaults). Callers with shorter timeouts
// (e.g. agent-core's httpx client) would time out on every single send,
// even though the message eventually went out. The handler must now
// acknowledge immediately and do the humanized send in the background.
func TestSendTextRespondsBeforeAntiBanDelayCompletes(t *testing.T) {
	fp := &fakeProvider{sendTextCall: make(chan struct{})}
	server, _ := newTestServer(t, fp)

	body := strings.NewReader(`{"number":"5511999999999","text":"hi"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/message/sendText/test", body)
	rec := httptest.NewRecorder()

	start := time.Now()
	server.ServeHTTP(rec, req)
	elapsed := time.Since(start)

	if elapsed > 500*time.Millisecond {
		t.Fatalf("handler blocked for %v — anti-ban delay (1.5s configured) leaked into the HTTP response", elapsed)
	}

	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202 Accepted, got %d: %s", rec.Code, rec.Body.String())
	}

	var resp map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}
	if resp["status"] != "queued" {
		t.Fatalf("expected status=queued, got %v", resp["status"])
	}

	// The actual send must still happen, just asynchronously.
	select {
	case <-fp.sendTextCall:
	case <-time.After(5 * time.Second):
		t.Fatal("SendText was never called in the background")
	}
}

// TestSendTextRetriesTransientFailures is a regression test for a second
// issue introduced by the async fix above: since nothing waits on the
// result of a background send anymore, a transient failure (observed in
// production as repeated "usync query timed out" errors from whatsmeow)
// would silently drop the message with no retry and no visibility. The
// handler must retry a few times before giving up.
func TestSendTextRetriesTransientFailures(t *testing.T) {
	fp := &fakeProvider{sendTextCall: make(chan struct{}), failTimes: 2}
	server, _ := newTestServer(t, fp)

	body := strings.NewReader(`{"number":"5511999999999","text":"hi"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/message/sendText/test", body)
	rec := httptest.NewRecorder()
	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202 Accepted, got %d: %s", rec.Code, rec.Body.String())
	}

	select {
	case <-fp.sendTextCall:
	case <-time.After(10 * time.Second):
		t.Fatalf("SendText never succeeded after retries (attempts so far: %d)", fp.attemptCount())
	}

	if got := fp.attemptCount(); got != 3 {
		t.Fatalf("expected 3 attempts (2 failures + 1 success), got %d", got)
	}
}
