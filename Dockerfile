FROM python:3.9
ENV PYTHONUNBUFFERED 1
RUN apt-get update && apt-get install -y udev
COPY ./requirements.txt /
RUN pip install -r requirements.txt
WORKDIR /app
ADD ./code /app/
