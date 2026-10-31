FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
# opentelemetry-instrument wraps the process: it detects the instrumentation
# packages installed above and patches fastapi/sqlalchemy/logging at startup,
# before app.main is even imported. No code changes needed for auto-instrumentation.
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
