# Utilise l'image officielle Python d'Apify (compatible Playwright)
FROM apify/actor-python-playwright:3.11

# Copie le fichier des dépendances
COPY requirements.txt ./

# Installation des bibliothèques
RUN pip install --no-cache-dir -r requirements.txt

# Copie le reste de ton code
COPY . ./

# Commande de lancement
CMD ["python3", "main.py"]
