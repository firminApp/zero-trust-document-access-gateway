FROM python:3.11-slim

# Tesseract + pack français (OCR_LANG=fra) et les bibliothèques natives
# attendues par OpenCV headless.
#
# `fonts-dejavu-core` sert au rendu du corpus dégradé : sans vraie police
# TrueType, `corpus/degrade.py` retombe sur la police vectorielle d'OpenCV, qui
# perd le point du « i » et multiplie par cinq le CER mesuré.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-fra \
      libglib2.0-0 \
      libgl1 \
      curl \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt requirements-camembert.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Modèle spaCy français. `_lg` donne un net gain sur les patronymes et
# toponymes par rapport à `_sm` ; on installe le petit en repli pour que le
# service démarre même si le téléchargement du grand échoue.
RUN python -m spacy download fr_core_news_sm \
    && (python -m spacy download fr_core_news_lg || \
        echo "fr_core_news_lg indisponible, repli sur fr_core_news_sm")

# Backend CamemBERT (ADR n°4). Désactivable pour une image légère :
#   docker compose build --build-arg AVEC_CAMEMBERT=false moteur-ia
ARG AVEC_CAMEMBERT=true
RUN if [ "$AVEC_CAMEMBERT" = "true" ]; then \
      pip install --no-cache-dir -r requirements-camembert.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu ; \
    fi

COPY app ./app
COPY evaluation ./evaluation

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD curl -fsS http://localhost:8000/sante || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
