FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8001
# Apply migrations, load synthetic engineering history on first run, then serve.
CMD ["sh", "-c", "alembic upgrade head && python -m sdlc.synth --if-empty && uvicorn sdlc.api:app --host 0.0.0.0 --port 8001 --reload"]
