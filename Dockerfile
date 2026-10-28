FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vacancy_agent vacancy_agent
COPY static static

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "vacancy_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
