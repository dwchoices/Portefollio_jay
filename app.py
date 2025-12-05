import requests
import smtplib
import ssl
from email.mime.text import MIMEText
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
from flask import Flask, jsonify, render_template
import threading
import time
from typing import List, Dict, Union, Any, Optional
from dotenv import load_dotenv # Importation de dotenv
import os

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Configuration centralisée dans une classe
class Config:
    # Lecture sécurisée depuis les variables d'environnement, avec des valeurs par défaut/placeholders
    EMAIL_FROM = os.getenv("EMAIL_FROM", "workflow@domain.com")
    EMAIL_TO = os.getenv("EMAIL_TO", "client@domain.com")
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.domain.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER", "user")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "password")
    SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "https://hooks.slack.com/services/XXXXX/YYYYY/ZZZZZ")
    GOOGLE_SHEET_JSON = os.getenv("GOOGLE_SHEET_JSON", "credentials.json")
    SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")
    MAX_DEPTH = int(os.getenv("MAX_DEPTH", 5))
    INTERVAL = int(os.getenv("INTERVAL", 60))
    ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", 1000))

# Initialisation de la configuration
config = Config()

logging.basicConfig(filename='workflow_pro.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

dashboard_data: List[Dict[str, Any]] = []
app = Flask(__name__)

# Gestionnaire d'API utilisant une session requests pour l'efficacité
class ApiManager:
    def __init__(self):
        self.session = requests.Session()

    def fetch_data(self, api_url: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status() # Gère les erreurs HTTP (404, 500, etc.)
            logging.info(f"API appelée : {api_url}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API {api_url} : {e}")
            dashboard_data.append({
                "timestamp": str(datetime.now()), "api": api_url, "value": "Erreur API",
                "status": "Erreur", "max_value": "N/A", "min_value": "N/A", "avg_value": "N/A"
            })
            return None

# Gestionnaire de Notifications et Google Sheets regroupés ou séparés selon la préférence
class WorkflowService:
    def __init__(self, config: Config):
        self.config = config
        self.api_manager = ApiManager()
        self.gs_sheet = self._setup_google_sheet()
        self.ssl_context = ssl.create_default_context()

    def _setup_google_sheet(self):
        try:
            scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.config.GOOGLE_SHEET_JSON, scope)
            client = gspread.authorize(creds)
            return client.open(self.config.SHEET_NAME).sheet1
        except Exception as e:
            logging.error(f"Erreur d'authentification Google Sheet : {e}")
            return None

    def send_email(self, value: Union[int, float, str]):
        try:
            msg = MIMEText(f"Valeur extraite : {value}")
            msg['Subject'] = "Résultat API conditionnelle ultime PRO 2025"
            msg['From'] = self.config.EMAIL_FROM
            msg['To'] = self.config.EMAIL_TO
            with smtplib.SMTP(self.config.SMTP_SERVER, self.config.SMTP_PORT) as server:
                server.starttls(context=self.ssl_context)
                server.login(self.config.SMTP_USER, self.config.SMTP_PASSWORD)
                server.send_message(msg)
            logging.info(f"Email envoyé : {value}")
        except Exception as e:
            logging.error(f"Erreur envoi email : {e}")

    def send_slack(self, value: Union[int, float, str]):
        try:
            payload = {"text": f"Valeur extraite : {value}"}
            # Utilisation de la session API Manager pour les requêtes
            self.api_manager.session.post(self.config.SLACK_WEBHOOK, json=payload, timeout=5)
            logging.info(f"Slack notifié : {value}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur Slack : {e}")

    def update_google_sheet(self, value: Union[int, float, str]):
        if self.gs_sheet:
            try:
                self.gs_sheet.append_row([value, str(datetime.now())])
                logging.info(f"Google Sheet mise à jour : {value}")
            except Exception as e:
                logging.error(f"Erreur lors de l'écriture Google Sheet : {e}")

    def find_numbers(self, obj: Any) -> List[Union[int, float]]:
        results = []
        if isinstance(obj, dict):
            for v in obj.values():
                results.extend(self.find_numbers(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self.find_numbers(item))
        elif isinstance(obj, (int, float)):
            results.append(obj)
        return results

    def select_next_api(self, numbers: List[Union[int, float]], depth: int) -> Optional[str]:
        if depth >= self.config.MAX_DEPTH or not numbers:
            return None
        # Simplified calculation for next API selection
        avg_value = sum(numbers)/len(numbers)
        if avg_value < 50:
            return "https://api.publicapis.org/entries"
        elif avg_value < 100:
            return "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        else:
            return "https://api.exchangerate.host/latest"

    def recursive_workflow(self, api_url: str, depth: int = 0):
        if api_url is None:
            logging.info("Fin du workflow ultime PRO 2025 ✅")
            return
        
        data = self.api_manager.fetch_data(api_url)
        if data is None:
            return
        
        numbers = self.find_numbers(data)
        
        # Safe extraction of metrics
        value = numbers[0] if numbers else "N/A"
        status = "OK"
        
        if numbers:
            max_value = max(numbers)
            min_value = min(numbers)
            avg_value = round(sum(numbers)/len(numbers), 2)

            self.send_email(value)
            self.send_slack(value)
            self.update_google_sheet(value)
            
            if value != "N/A" and value >= self.config.ALERT_THRESHOLD:
                logging.warning(f"Valeur critique détectée : {value}")
                status = "ALERTE"
        else:
            max_value, min_value, avg_value = "N/A", "N/A", "N/A"


        dashboard_data.append({
            "timestamp": str(datetime.now()), "api": api_url, "value": value,
            "status": status, "max_value": max_value, "min_value": min_value,
            "avg_value": avg_value
        })

        next_api = self.select_next_api(numbers, depth+1)
        self.recursive_workflow(next_api, depth+1)

# Initialisation du service principal
workflow_service = WorkflowService(config)

# Thread continu
def start_workflow():
    initial_api = "https://api.publicapis.org/random"
    while True:
        logging.info("=== Nouvelle exécution du workflow PRO 2025 ===")
        # Appel via l'instance de la classe
        workflow_service.recursive_workflow(initial_api)
        logging.info(f"Attente {config.INTERVAL} secondes avant prochaine exécution")
        time.sleep(config.INTERVAL)

# Dashboard Flask (inchangé)
@app.route("/")
def dashboard():
    # Nécessite toujours un fichier templates/dashboard.html
    recent = dashboard_data[-20:][::-1]
    return render_template("dashboard.html", data=recent)

@app.route("/api/latest")
def api_latest():
    return jsonify(dashboard_data[-20:][::-1])

if __name__ == "__main__":
    workflow_thread = threading.Thread(target=start_workflow)
    workflow_thread.daemon = True
    workflow_thread.start()
    app.run(host="0.0.0.0", port=5000)
