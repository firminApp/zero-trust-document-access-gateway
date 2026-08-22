# --- Étape de construction ---------------------------------------------------
FROM node:20-alpine AS construction

WORKDIR /srv
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

# --- Étape de service --------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=construction /srv/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
