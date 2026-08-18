# Image cho tool moodle-mssql2pg.
# Khong dung dimitri/pgloader:latest vi image do la Debian 11 (Python 3.9) va apt
# da hong keyring -> tool yeu cau Python >= 3.10.
# Debian bookworm co san pgloader 3.6.7~devel (dung version voi image maintainer)
# va Python 3.11.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      pgloader \
      freetds-bin freetds-common \
      python3 python3-pip \
      postgresql-client \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# FreeTDS mac dinh dung client charset ISO-8859-1. Source LMS_PTSC co collation
# SQL_Latin1_General_CP1_CI_AS (CP1252) va 1772 cot nvarchar chua tieng Viet:
# neu de ISO-8859-1 thi pgloader nhan byte khong hop le UTF-8 (INVALID-UTF8-
# CONTINUATION-BYTE) va tieng Viet bi hong. Ep UTF-8 + TDS 7.4 cho SQL Server 2019.
RUN sed -i 's/^\ttds version = auto/\ttds version = 7.4\n\tclient charset = UTF-8/' \
      /etc/freetds/freetds.conf \
    && grep -A2 '^\[global\]' /etc/freetds/freetds.conf

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
RUN pip3 install --no-cache-dir --break-system-packages ".[drivers]"

ENTRYPOINT ["moodle-mssql2pg"]
CMD ["--help"]
