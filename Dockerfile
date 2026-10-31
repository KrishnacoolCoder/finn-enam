FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    FINN_DATA_DIR=/home/user/app/data \
    FINN_AUTO_POLL_MINUTES=0 \
    FINN_AUTO_ANNOUNCEMENTS=1

RUN useradd --create-home --uid 1000 user
WORKDIR /home/user/app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
USER user

EXPOSE 7860
CMD ["uvicorn", "app.deploy:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
