FROM python:3.11-slim-bookworm
ENV TZ=Europe/Moscow
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python3", "./main.py"]
