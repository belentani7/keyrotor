# scripts

Utilidades de linea de comandos.

| Script | Que hace |
|---|---|
| `fetch_open_data.py` | Regenera `open-data/llm-models.{json,csv}` desde la API publica de OpenRouter. Solo libreria estandar. |
| `secret_scan.py` | Escanea el repo buscando patrones de claves/secretos. Lo ejecuta el CI. |
| `find_deploys.py` | Ayuda a localizar despliegues. |

```bash
python scripts/fetch_open_data.py
python scripts/secret_scan.py
```
