FROM python:3.12-slim

WORKDIR /app

# System deps: build toolchain for dydx-v4-client, plus Node for the Prisma CLI.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    nodejs \
    npm \
    && npm install -g prisma \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate the Prisma Python client from the schema at build time.
RUN prisma generate --schema prisma/schema.prisma

EXPOSE 8000

CMD ["sh", "-c", "prisma migrate deploy --schema prisma/schema.prisma && uvicorn app:app --host 0.0.0.0 --port 8000"]
