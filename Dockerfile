# Dockerfile for building the image. Build context = repository root:
#   docker build -f build/Dockerfile .
# The .dockerignore in the repository root is an allowlist of what gets copied into the image.
FROM python:3.12-alpine

# Runtime packages; python-ldap needs the OpenLDAP/SASL client libraries.
RUN apk add --no-cache bash ncurses flock libldap libsasl

WORKDIR /app
COPY Pipfile /app/
# Compilers and headers are only needed to build python-ldap; they are removed in the same layer.
RUN apk add --no-cache --virtual .build-deps gcc musl-dev openldap-dev \
    && pip install --no-cache-dir --upgrade pip pipenv \
    && PIPENV_PYTHON=/usr/local/bin/python3.12 pipenv lock \
    && PIPENV_PYTHON=/usr/local/bin/python3.12 pipenv install --system --deploy \
    && pip uninstall -y pipenv \
    && rm -rf /root/.cache \
    && apk del .build-deps

# Uncomment to append your CA cert for TLS connections (i.e. LDAPS). Place the crt file in the repository
# root and allow it in .dockerignore (add a line "!ca.crt").
#COPY ca.crt /usr/local/share/ca-certificates/ca.crt
#RUN cat /usr/local/share/ca-certificates/ca.crt >> /etc/ssl/certs/ca-certificates.crt

COPY . /app/

# Unprivileged user (uid 1000). To read the mail log the container needs the log file's group
# (docker compose: group_add ${MAIL_LOG_GID}, default 4 = "adm" on Debian/Ubuntu).
# /app must be writable for the parser's lock file; /app/instance keeps the generated secret key.
RUN sed -i 's/\r$//' /app/run.sh \
    && chmod 755 /app/run.sh \
    && adduser -D -H -u 1000 mlp \
    && mkdir -p /app/instance \
    && chown mlp:mlp /app /app/instance \
    && chmod 700 /app/instance
USER mlp

ENV PYTHONUNBUFFERED=1
CMD ["/app/run.sh", "prod"]
