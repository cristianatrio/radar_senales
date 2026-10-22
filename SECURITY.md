# Seguridad

## Cómo está protegido el proyecto

- **Sin secretos en el repositorio.** Las credenciales de Telegram y Ripio se leen de variables
  de entorno o de archivos locales ignorados por git (`telegram_config.txt`, `ripio_config.txt`).
  Las plantillas versionadas (`*.example.txt`, `.env.example`) solo tienen nombres de variables.
- **Claves de solo lectura.** La integración con Ripio nunca opera: solo consulta saldos. La guía
  pide crear la API key sin permisos de retiro ni de operación y, si se puede, restringida por IP.
- **Datos privados fuera del repo.** `output/` (base de datos, posiciones, CSV reales) y el PBIX
  personal están en `.gitignore`. El informe público usa únicamente datos sintéticos.
- **Tests que lo verifican.** `tests/test_seguridad.py` falla si aparece un patrón de credencial
  en un archivo público o si una plantilla trae valores; `tests/test_pbip.py` comprueba que el
  modelo de Power BI no incluya tablas privadas ni rutas personales. La suite bloquea la red.
- **Dependencias fijadas y auditadas.** `requirements.txt` + `constraints.txt` fijan todas las
  versiones; Dependabot avisa de actualizaciones y vulnerabilidades. La CI corre `ruff` con las
  reglas de seguridad de Bandit y tiene permisos mínimos (`contents: read`).

## Si encontrás un problema

Abrí un *issue* privado con la pestaña **Security → Report a vulnerability** del repositorio, o
escribí al autor por GitHub. No publiques credenciales ni datos de terceros en issues públicos.

## Si una credencial se filtró

Revocala primero (Telegram: `/revoke` en @BotFather; Ripio: borrar la API key en la cuenta) y
recién después limpiá el historial. Borrar el archivo del repo no alcanza.
