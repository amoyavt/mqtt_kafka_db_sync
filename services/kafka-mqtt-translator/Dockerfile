FROM python:3.11-slim

WORKDIR /app

# Copy project files
COPY translator.py ./

# Install dependencies directly and create user in single layer
RUN pip install --no-cache-dir kafka-python==2.0.2 paho-mqtt==1.6.1 && \
    useradd --create-home --shell /bin/bash translator && \
    rm -rf /root/.cache /tmp/* /var/tmp/* && \
    apt-get autoremove -y && \
    apt-get clean

USER translator

CMD ["python", "translator.py"]