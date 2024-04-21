FROM ubuntu:latest

RUN mkdir -p /app/
RUN apt-get update 
RUN apt-get upgrade -y
RUN apt-get install -y git
RUN git clone https://github.com/observerkei/aimi.git /app/aimi
WORKDIR /app/aimi/
RUN git submodule update --init --recursive
RUN git submodule update --remote

RUN ls /app/aimi
WORKDIR /app/aimi/run
RUN pwd
RUN ls
RUN chmod +x ./build_environment.sh
RUN bash -x ./build_environment.sh

RUN echo "build success"