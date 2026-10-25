FROM alpine:3.21
RUN apk add --no-cache python3 novnc websockify
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
