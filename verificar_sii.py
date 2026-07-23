#!/usr/bin/env python3
"""Script para verificar página certificación SII"""
import subprocess
import sys

# Instalar playwright si no está
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Instalando playwright...")
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    from playwright.sync_api import sync_playwright

def verificar_sii():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("Abriendo página certificación SII...")
        page.goto("https://maullin.sii.cl/cvc/dte/certificacion_dte.html", timeout=60000)
        
        print("Esperando carga completa...")
        page.wait_for_load_state("networkidle")
        
        print("\n=== Contenido de la página ===")
        print(page.title())
        print("\nURL actual:", page.url)
        
        # Verificar si hay elementos clave
        elementos = page.query_selector_all("form, input, button, a")
        print(f"\nElementos encontrados: {len(elementos)}")
        
        # Tomar screenshot
        page.screenshot(path="/tmp/sii_certificacion.png")
        print("\nScreenshot guardado en: /tmp/sii_certificacion.png")
        
        # Esperar para que puedas ver
        print("\nNavegador abierto por 30 segundos...")
        page.wait_for_timeout(30000)
        
        browser.close()

if __name__ == "__main__":
    verificar_sii()
