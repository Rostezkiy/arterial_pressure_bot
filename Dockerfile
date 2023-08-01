FROM python:3.11-slim-bookworm
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python3", "./main.py"]
