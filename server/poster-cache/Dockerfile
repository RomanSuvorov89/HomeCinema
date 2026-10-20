FROM python:3.13-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY server.py kinoafisha_posters.py /app/
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 9121
CMD ["python", "-u", "/app/server.py"]
