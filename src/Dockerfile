FROM python:3.10.7

COPY . /app
WORKDIR /app

RUN pip install -r requirements.txt
STOPSIGNAL SIGINT

CMD ["python", "-u", "src/run.py"]