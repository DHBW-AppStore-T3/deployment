# Alpine 3.24 (3.21 is supported until 2026-11-01 only).
FROM alpine:3.24
# Security updates newer than the base image at every CI build: novnc-proxy.yml passes SECURITY_REFRESH (the run id),
# so this step never comes from the build cache.
ARG SECURITY_REFRESH
RUN apk upgrade --no-cache && apk add --no-cache python3 py3-aiohttp novnc
COPY proxy.py /proxy.py
USER 1000:1000
EXPOSE 8080
ENTRYPOINT ["python3", "/proxy.py"]
