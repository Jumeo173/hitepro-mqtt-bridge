FROM python:3.11-alpine

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev \
    && apk add --no-cache curl

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && apk del .build-deps

COPY app/ /app/

CMD ["python3", "-u", "/app/main.py"]
