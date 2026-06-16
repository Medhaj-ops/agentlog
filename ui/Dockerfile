FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx
COPY app.py .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]
