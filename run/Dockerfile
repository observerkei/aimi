FROM ubuntu:latest

RUN mkdir -p /app/aimi

COPY ./ /app/aimi/*
RUN ls /app/aimi
RUN cd /app/aimi/run 
#&& chmod +x build_environment.sh && /bin/bash build_environment.sh 

RUN echo "build success"

