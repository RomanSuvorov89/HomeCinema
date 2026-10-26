FROM python:3.13-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY server.py kinoafisha_posters.py /app/
# Sources may be 0600 after installation with umask 077.
# Only application code is public inside the image; mounted data stays private.
RUN chmod -R a+rX /app
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 9121
CMD ["python", "-u", "/app/server.py"]
