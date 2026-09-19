# يضمن وجود محرك التشكيل المتقدم (raqm/HarfBuzz/FriBiDi) على أي جهاز/استضافة
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libraqm0 libfribidi0 libharfbuzz0b && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 2 -t 120 -b 0.0.0.0:${PORT} app:app"]
