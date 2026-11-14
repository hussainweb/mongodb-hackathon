FROM python:3.14-slim

ARG API_VERSION=v1
ENV API_VERSION=${API_VERSION}
ENV SERVICE_NAME=billing-worker
ENV PORT=8080

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 8080
CMD ["python", "/app/server.py"]
