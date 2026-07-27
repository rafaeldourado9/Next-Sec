package provider

import "testing"

// TestToJIDPreservesServerForFullJIDs is a regression test for a production
// bug: incoming senders are increasingly identified by LID (a numeric
// namespace distinct from phone numbers, JID server "lid") rather than the
// classic phone-number JID ("s.whatsapp.net"). toJID used to strip everything
// but digits and always rebuild a "@s.whatsapp.net" JID, so replying to a LID
// sender silently targeted a nonexistent phone-number account — the message
// never arrived, with no visible error to the caller.
func TestToJIDPreservesServerForFullJIDs(t *testing.T) {
	cases := []struct {
		name       string
		input      string
		wantUser   string
		wantServer string
	}{
		{
			name:       "full LID JID is parsed as-is",
			input:      "104200855892049@lid",
			wantUser:   "104200855892049",
			wantServer: "lid",
		},
		{
			name:       "full phone JID is parsed as-is",
			input:      "5511999999999@s.whatsapp.net",
			wantUser:   "5511999999999",
			wantServer: "s.whatsapp.net",
		},
		{
			name:       "bare phone number falls back to phone JID",
			input:      "5511999999999",
			wantUser:   "5511999999999",
			wantServer: "s.whatsapp.net",
		},
		{
			name:       "bare phone number with formatting is cleaned",
			input:      "+55 (11) 99999-9999",
			wantUser:   "5511999999999",
			wantServer: "s.whatsapp.net",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			jid := toJID(tc.input)
			if jid.User != tc.wantUser {
				t.Errorf("User = %q, want %q", jid.User, tc.wantUser)
			}
			if jid.Server != tc.wantServer {
				t.Errorf("Server = %q, want %q", jid.Server, tc.wantServer)
			}
		})
	}
}
