FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY ui/backend/requirements.txt /tmp/ui-backend-requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r /tmp/ui-backend-requirements.txt

COPY . .

EXPOSE 8090

CMD ["uvicorn", "ui.backend.app:app", "--host", "0.0.0.0", "--port", "8090"]
