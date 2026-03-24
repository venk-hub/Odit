FROM mitmproxy/mitmproxy:10.3.1

RUN mkdir -p /addon /data/proxy_flows /data/certs

COPY mitm_addon.py /addon/mitm_addon.py

EXPOSE 8080

ENV DATA_DIR=/data

CMD ["mitmdump", \
     "--listen-host", "0.0.0.0", \
     "--listen-port", "8080", \
     "-s", "/addon/mitm_addon.py", \
     "--set", "ssl_insecure=true", \
     "--set", "connection_strategy=lazy", \
     "--set", "confdir=/data/certs"]
