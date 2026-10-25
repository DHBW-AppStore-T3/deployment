FROM alpine:3.21
RUN apk add --no-cache python3 py3-aiohttp novnc
COPY proxy.py /proxy.py
USER 1000:1000
EXPOSE 8080
ENTRYPOINT ["python3", "/proxy.py"]
