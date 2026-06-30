FROM python:3.12-slim-bookworm

# ── Driver ODBC 18 para SQL Server + dependencias de compilación ──────────────
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl gnupg2 apt-transport-https ca-certificates \
      gcc g++ unixodbc-dev \
 && curl -sSL -O https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
 && dpkg -i packages-microsoft-prod.deb \
 && rm packages-microsoft-prod.deb \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# ── Dependencias Python (capa cacheable) ──────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código de la aplicación ───────────────────────────────────────────────────
COPY . .

# El entrypoint y la app se ejecutan desde app/ (imports tipo `from utils import`)
RUN sed -i 's/\r$//' /code/docker-entrypoint.sh \
 && chmod +x /code/docker-entrypoint.sh \
 && mkdir -p /code/app/logs

WORKDIR /code/app
EXPOSE 8000

ENTRYPOINT ["bash", "/code/docker-entrypoint.sh"]
