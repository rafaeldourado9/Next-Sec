FROM node:20-alpine AS builder
WORKDIR /app

# Instala dependências com lockfile (mais rápido e determinístico que npm install)
COPY package.json package-lock.json* ./
RUN npm install --prefer-offline

# Build args para variáveis Vite (injetadas no bundle em tempo de build)
ARG VITE_APP_NAME=VMS
ARG VITE_ACCENT_COLOR=#3B82F6
# VITE_API_URL deixado vazio — em produção o frontend usa /api/v1 via nginx
ARG VITE_API_URL=

ENV VITE_APP_NAME=$VITE_APP_NAME
ENV VITE_ACCENT_COLOR=$VITE_ACCENT_COLOR
ENV VITE_API_URL=$VITE_API_URL

COPY . .
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1
