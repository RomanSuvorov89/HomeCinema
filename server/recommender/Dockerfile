FROM python:3.13-alpine
RUN apk add --no-cache curl
WORKDIR /app
COPY kp_sync.py /app/kp_sync.py
COPY episode_schedule.py /app/episode_schedule.py
COPY kinoafisha.py /app/kinoafisha.py
COPY home_cache.py /app/home_cache.py
COPY candidate_engine.py /app/candidate_engine.py
COPY review_api.py /app/review_api.py
COPY track_preferences.py /app/track_preferences.py
COPY track-memory.js /app/track-memory.js
COPY platform_corrections.json /app/platform_corrections.json
COPY client-defaults.js /app/client-defaults.js
COPY kinopoisk.js /app/kinopoisk.js
COPY schema.sql /app/schema.sql
COPY RECOMMENDER.md /app/RECOMMENDER.md
ENV SERVE=1 DATA_FILE=/data/kinopoisk.json REFRESH_SECONDS=86400
EXPOSE 9120
CMD ["python", "/app/kp_sync.py"]
