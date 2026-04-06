FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY reviewer/ ./reviewer/
COPY .reviewer.yaml .

ENTRYPOINT ["python", "-m", "reviewer.main"]
