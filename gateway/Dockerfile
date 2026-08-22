# Le contexte de construction est la racine du dépôt, et non `gateway/` :
# l'image doit embarquer `db/migrations` pour que `make seed` applique les
# migrations depuis le conteneur, sans client psql sur la machine hôte.
#
#   docker build -f gateway/Dockerfile .

# --- Étape de construction ---------------------------------------------------
FROM node:20-alpine AS construction

WORKDIR /srv
COPY gateway/package.json gateway/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY gateway/tsconfig.json gateway/nest-cli.json ./
COPY gateway/src ./src
RUN npm run build

# --- Étape d'exécution -------------------------------------------------------
FROM node:20-alpine

RUN apk add --no-cache curl

WORKDIR /srv

COPY gateway/package.json gateway/package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force

COPY --from=construction /srv/dist ./dist
COPY db ./db

ENV NODE_ENV=production \
    MIGRATIONS_DIR=/srv/db/migrations

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://localhost:3000/sante || exit 1

CMD ["node", "dist/main.js"]
