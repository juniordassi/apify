FROM apify/actor-python-playwright-chrome:3.11

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

CMD ["python3", "main.py"]