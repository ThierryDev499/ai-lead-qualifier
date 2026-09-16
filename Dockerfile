FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd -m appuser
COPY . .
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8104
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8104"]
