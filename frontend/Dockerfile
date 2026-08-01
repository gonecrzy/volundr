FROM node:22-slim AS build

WORKDIR /app
ARG VITE_VOLUNDR_GENERATION_MODE=advanced
ARG VITE_VOLUNDR_CHAT_FIRST=true
ENV VITE_VOLUNDR_GENERATION_MODE=${VITE_VOLUNDR_GENERATION_MODE}
ENV VITE_VOLUNDR_CHAT_FIRST=${VITE_VOLUNDR_CHAT_FIRST}

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
