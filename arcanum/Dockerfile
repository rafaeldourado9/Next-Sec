FROM golang:1.25-alpine AS builder

RUN apk add --no-cache gcc musl-dev git

WORKDIR /build
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=1 go build -o /gateway ./cmd/gateway

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /gateway /gateway

VOLUME /data
ENV GATEWAY_DB_PATH=/data
EXPOSE 3100

CMD ["/gateway"]
