# Dockerfile for deploy: Python dependencies only (the application code is not copied).
FROM python:3.12-alpine
RUN apk add --no-cache bash ncurses flock libldap libsasl
WORKDIR /app
COPY Pipfile /app/
RUN apk add --no-cache --virtual .build-deps gcc musl-dev openldap-dev \
    && pip install --no-cache-dir --upgrade pip pipenv \
    && PIPENV_PYTHON=/usr/local/bin/python3.12 pipenv lock \
    && PIPENV_PYTHON=/usr/local/bin/python3.12 pipenv install --system --deploy \
    && pip uninstall -y pipenv \
    && rm -rf /root/.cache \
    && apk del .build-deps
# uncomment to append your ca cert for TLS connections i.e. LDAPS, place crt file in folder with Dockerfile
#COPY ca.crt /usr/local/share/ca-certificates/ca.crt
#RUN cat /usr/local/share/ca-certificates/ca.crt >> /etc/ssl/certs/ca-certificates.crt
RUN adduser -D -H -u 1000 mlp && chown mlp:mlp /app
USER mlp
