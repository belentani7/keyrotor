# open-data — catalogo abierto de modelos LLM

Pack de datos abiertos que describe el catalogo publico de modelos disponibles
en OpenRouter: identificador, contexto, precio por millon de tokens y modalidad.

## Ficheros

| Fichero | Descripcion |
|---|---|
| `llm-models.json` | Modelos con metadatos + bloque `meta` de generacion |
| `llm-models.csv` | El mismo pack en tabla (`id`, `name`, `context_length`, precios, `modality`) |

## Fuente

- Endpoint: <https://openrouter.ai/api/v1/models>
- Publico: **no requiere clave de API**.
- Los precios y metadatos los publica OpenRouter y cada proveedor.
- Los precios van en **USD por millon de tokens**
  (`prompt_usd_per_mtok`, `completion_usd_per_mtok`), convertidos desde el
  valor por token que devuelve la API.

## Regenerar

```bash
python scripts/fetch_open_data.py            # todos los modelos
python scripts/fetch_open_data.py --limit 50 # solo 50
```

El script usa **solo la libreria estandar** (sin dependencias).

## Licencia

Los datos pertenecen a OpenRouter y a los proveedores de cada modelo; se
incluyen como referencia informativa. Revisa los terminos de OpenRouter antes
de redistribuirlos. El *codigo* que genera este pack es MIT, como el resto de
`keyrotor`.

---
*Fecha de generacion: ver `meta.generated_at` en `llm-models.json`.*
