# Contribuindo com o Arcanum API

Obrigado por considerar contribuir com o Arcanum API! Este documento explica como participar do projeto.

## Como contribuir

### Reportando bugs

1. Verifique se o bug ja nao foi reportado nas [Issues](https://github.com/rafaeldourado9/arcanum/issues)
2. Abra uma nova issue com:
   - Titulo claro e descritivo
   - Passos para reproduzir
   - Comportamento esperado vs atual
   - Versao do Arcanum, Go, e sistema operacional
   - Logs relevantes

### Sugerindo melhorias

Abra uma issue com a tag `enhancement` descrevendo:
- O que voce gostaria que fosse adicionado
- Por que isso seria util
- Como voce imagina a implementacao

### Pull Requests

1. Fork o repositorio
2. Crie uma branch: `git checkout -b feat/minha-feature`
3. Faca suas alteracoes seguindo o estilo do projeto
4. Escreva testes para o codigo novo
5. Garanta que tudo compila: `go build ./...`
6. Garanta que os testes passam: `go test ./...`
7. Commit com mensagem descritiva (Conventional Commits):
   - `feat: adiciona suporte a stickers`
   - `fix: corrige reconnect apos timeout`
   - `docs: atualiza README com novo endpoint`
8. Push e abra um Pull Request

## Estilo de codigo

- Go idiomatico — siga as convencoes do [Effective Go](https://go.dev/doc/effective_go)
- Sem frameworks pesados — stdlib + chi + whatsmeow
- Erros explicitos — sem panics, sem swallow de erros
- Interfaces pequenas — um provider nao precisa saber sobre HTTP
- Anti-ban obrigatorio — nunca enviar mensagem sem delay/presence

## Estrutura do projeto

```
cmd/gateway/main.go          → Entry point
internal/
  config/                    → Configuracao via env vars
  provider/                  → Interface + implementacao whatsmeow
  antiban/                   → Rate limiter + delays humanizados
  webhook/                   → Forwarding com HMAC
  instance/                  → Gerenciador multi-instancia
  api/                       → Handlers HTTP + Swagger
  media/                     → Helpers base64
```

## Licenca

Ao contribuir, voce concorda que suas contribuicoes serao licenciadas sob a [Licenca MIT](LICENSE).
