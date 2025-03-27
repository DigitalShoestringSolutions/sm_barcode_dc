FROM python:3.13
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y udev

COPY ./code/requirements.txt /
RUN pip3 install -r requirements.txt
WORKDIR /app
COPY --from=solution_config module_config/ /app/module_config
ADD ./code/ /app