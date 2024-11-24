FROM python:3.12-alpine

RUN apk add --no-cache tzdata

COPY requirements.txt /opt
RUN pip install --no-cache -r /opt/requirements.txt

COPY docker/entrypoint.py /imap2imap/docker/
COPY imap2imap.py /imap2imap/

WORKDIR /imap2imap

ENV PYTHONPATH /imap2imap

USER nobody

ENTRYPOINT ["python" ,"-u", "docker/entrypoint.py"]
