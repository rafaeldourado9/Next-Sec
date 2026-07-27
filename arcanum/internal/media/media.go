// Package media fornece utilitarios para conversao de midia entre formatos binario e base64.
// Usado pelo webhook forwarder (encode para enviar no JSON) e pelos handlers de envio (decode do request).
package media

import "encoding/base64"

// ToBase64 converte bytes brutos para string base64 (standard encoding).
func ToBase64(data []byte) string {
	return base64.StdEncoding.EncodeToString(data)
}

// FromBase64 decodifica uma string base64 para bytes brutos.
func FromBase64(s string) ([]byte, error) {
	return base64.StdEncoding.DecodeString(s)
}
