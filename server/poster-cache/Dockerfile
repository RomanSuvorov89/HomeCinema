FROM python:3.13-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY server.py /app/server.py
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 9121
CMD ["python", "-u", "/app/server.py"]
