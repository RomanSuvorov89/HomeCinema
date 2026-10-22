FROM python:3.13-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY requirements-cloud.txt /app/requirements-cloud.txt
RUN pip install --no-cache-dir -r /app/requirements-cloud.txt
COPY cloud_disk.py connections.py test_cloud_disk.py /app/
COPY kp_sync.py profiles.py test_profiles.py /app/
COPY episode_schedule.py /app/episode_schedule.py
COPY kinoafisha.py /app/kinoafisha.py
COPY home_cache.py /app/home_cache.py
COPY candidate_engine.py /app/candidate_engine.py
COPY review_api.py /app/review_api.py
COPY facts.py /app/facts.py
COPY track_preferences.py /app/track_preferences.py
COPY track-memory.js /app/track-memory.js
COPY platform_corrections.json /app/platform_corrections.json
COPY client-defaults.js /app/client-defaults.js
COPY kinopoisk.js profiles-client.js /app/
COPY schema.sql /app/schema.sql
COPY RECOMMENDER.md /app/RECOMMENDER.md
ENV SERVE=1 DATA_FILE=/data/kinopoisk.json REFRESH_SECONDS=86400
EXPOSE 9120
CMD ["python", "/app/kp_sync.py"]
