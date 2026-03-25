FROM postgres:17-alpine

RUN apk add --no-cache python3 py3-pip \
    && python3 -m pip install --break-system-packages --no-cache-dir \
        alembic \
        sqlalchemy \
        asyncpg

WORKDIR /opt/lighthouse/db

COPY packages/db/alembic.ini /opt/lighthouse/db/alembic.ini
COPY packages/db/alembic /opt/lighthouse/db/alembic
COPY docker/postgres/initdb/run-alembic.sh /docker-entrypoint-initdb.d/run-alembic.sh
