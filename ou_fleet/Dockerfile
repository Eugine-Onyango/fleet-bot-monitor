FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY over_under_fleet.py .
CMD ["python", "-u", "over_under_fleet.py"]
