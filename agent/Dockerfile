FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    util-linux iproute2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ARG GIT_SHA=dev
RUN echo "$GIT_SHA" > /app/VERSION
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
