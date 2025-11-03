FROM python:3.12-slim

WORKDIR /app

ARG IMAGE_TAG
ENV IMAGE_TAG=$IMAGE_TAG

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5000
EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]